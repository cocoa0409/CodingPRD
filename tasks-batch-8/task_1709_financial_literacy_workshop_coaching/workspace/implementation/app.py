"""Flask entry point: app wiring, error handlers, serialized request handling."""
import os

from flask import Flask

import response
from db import LOCK
from errors import ApiError
from routes import register_routes


class LockMiddleware(object):
    """Serialize all requests through one RLock so concurrent test traffic
    observes atomic mutations."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with LOCK:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.err(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return response.err("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return response.err("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, ApiError):
            return response.err(e.error_id, e.message, e.http_status)
        return response.err("ERR_INVALID_REQUEST", str(e), 500)

    app.wsgi_app = LockMiddleware(app.wsgi_app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
