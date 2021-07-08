import os
import redis
import json
from datetime import datetime
from werkzeug.wrappers import Request, Response
from werkzeug.routing import Map, Rule
from werkzeug.exceptions import HTTPException, NotFound
from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.utils import redirect
from jinja2 import Environment, FileSystemLoader


class Board:
    def __init__(self, config):
        self.redis = redis.Redis(config['redis_host'], config['redis_port'])
        template_path = os.path.join(os.path.dirname(__file__), 'templates')
        self.jinja_env = Environment(loader=FileSystemLoader(template_path),
                                     autoescape=True)
        self.url_map = Map([
            Rule('/', endpoint='index'),
            Rule('/new_post', endpoint='new_post'),
            Rule('/<id>', endpoint='post_detail')
        ])

    def render_template(self, template_name, **context):
        t = self.jinja_env.get_template(template_name)
        return Response(t.render(context), mimetype='text/html')

    def dispatch_request(self, request):
        adapter = self.url_map.bind_to_environ(request.environ)
        try:
            endpoint, values = adapter.match()
            return getattr(self, f'on_{endpoint}')(request, **values)
        except HTTPException as e:
            return e

    def on_new_post(self, request):
        if request.method == 'POST':
            if required_fields_post(request):
                self.create_new_post(request)
                return redirect('/')
        return self.render_template('new_post.html')

    def on_post_detail(self, request, id):
        decoded_data = self.get_post(request, id)
        if not decoded_data:
            raise NotFound
        comments_list = self.get_comments(request, id)
        if request.method == 'POST':
            if required_fields_comment(request):
                self.create_new_comment(request, id)
        decoded_data['comments'] = comments_list[::-1]
        if decoded_data:
            return self.render_template(
                'post_detail.html',
                data=decoded_data
            )

    def on_index(self, request):
        redis_keys = self.redis.keys()
        posts = []
        for el in redis_keys:
            if el == b'0' or el == b'comments':
                continue
            encode_data = self.redis.hgetall(el)
            decoded_data = {}
            for key, val in encode_data.items():
                key = key.decode('utf-8')
                val = val.decode('utf-8')
                if key == 'text' and len(val) >= 90:
                    decoded_data[key] = val[:91] + '...'
                else:
                    decoded_data[key] = val
            posts.append(decoded_data)
        posts.sort(key=lambda x: x['id'], reverse=True)
        return self.render_template('posts.html', posts=posts)

    def create_new_post(self, request):
        data = {}
        id = self.redis.incr(0)
        now_date = datetime.now()
        data['id'] = str(id)
        data['author'] = request.form['author']
        data['title'] = request.form['title']
        data['text'] = request.form['text']
        data['posted_on'] = now_date.strftime('%d-%m-%Y %H:%M:%S')
        self.redis.hmset(id, data)

    def create_new_comment(self, request, id):
        comments = {}
        comments['author'] = request.form['author']
        comments['text'] = request.form['text']
        comments['post_id'] = id
        comments = json.dumps(comments)
        self.redis.rpush('comments', comments)

    def get_post(self, request, id):
        data = self.redis.hgetall(id)
        dec_data = {}
        for key, val in data.items():
            key = key.decode('utf-8')
            val = val.decode('utf-8')
            if type(val) != list:
                dec_data[key] = val
        return dec_data

    def get_comments(self, request, id):
        comments_list = []
        for comment in self.redis.lrange("comments", 0, -1):
            comment = comment.decode('utf-8')
            comment = json.loads(comment)
            if comment['post_id'] == str(id):
                comments_list.append(comment)
        return comments_list

    def wsgi_app(self, environ, start_response):
        request = Request(environ)
        response = self.dispatch_request(request)
        return response(environ, start_response)

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)


def required_fields_post(request: Request) -> bool:
    if request.form['author'] and request.form['title'] and request.form['text']:
        return True
    return False


def required_fields_comment(request: Request) -> bool:
    if request.form['author'] and request.form['text']:
        return True
    return False


def create_app(redis_host='localhost', redis_port=6379, with_static=True):
    app = Board({
        'redis_host': redis_host,
        'redis_port': redis_port
    })
    if with_static:
        app.wsgi_app = SharedDataMiddleware(app.wsgi_app, {
            '/static': os.path.join(os.path.dirname(__file__), 'static')
        })
    return app


if __name__ == '__main__':
    from werkzeug.serving import run_simple

    app = create_app()
    run_simple('127.0.0.1', 5000, app, use_debugger=True, use_reloader=True)
