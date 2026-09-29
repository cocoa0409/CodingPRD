"""Grocery Fuel Points & Cross-Banner Loyalty Redemption API.

Boots a completely empty in-memory store on every process start; nothing is
ever seeded, preloaded or read from disk.
"""
import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import register_routes

_LOCK = threading.RLock()


class SerialiseMiddleware(object):
    """One request at a time: the domain logic is a shared mutable dict graph."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with _LOCK:
            result = self.wsgi_app(environ, start_response)
            if isinstance(result, list):
                return result
            return list(result)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return response.error_response("ERR_METHOD_NOT_ALLOWED",
                                       "method not allowed for this path", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error_response("ERR_NOT_FOUND", "resource not found", 404)
        if exc.code == 405:
            return response.error_response("ERR_METHOD_NOT_ALLOWED",
                                           "method not allowed for this path", 405)
        if exc.code and 400 <= exc.code < 500:
            return response.error_response("ERR_INVALID_REQUEST",
                                           exc.description or "malformed request", 400)
        return response.error_response("ERR_INTERNAL", "internal server error", 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error_response("ERR_INTERNAL", "internal server error: %s" % exc, 500)

    app.wsgi_app = SerialiseMiddleware(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
