"""Equestrian Show Management API — Flask application factory and entrypoint.

State lives entirely in process memory (see ``core.Store``); nothing is ever
persisted to disk and no entity is seeded at startup.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import LOCK
from errors import ApiError
from response import error_response
from routes import BLUEPRINTS


class _SerializingMiddleware(object):
    """Serialise request handling so in-memory mutations stay consistent."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with LOCK:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        pass

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _handle_http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_NOT_FOUND", "Resource not found.", 404))
        if err.code == 405:
            return error_response(
                ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)
            )
        if err.code in (400, 415):
            return error_response(
                ApiError("ERR_INVALID_REQUEST", "The request body could not be parsed.", 422)
            )
        return error_response(
            ApiError("ERR_INVALID_REQUEST", err.description or "Request rejected.", 422)
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(err):  # pragma: no cover - defensive
        return error_response(
            ApiError("ERR_INTERNAL", "Unexpected server error: %s" % err, 500)
        )

    app.wsgi_app = _SerializingMiddleware(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
