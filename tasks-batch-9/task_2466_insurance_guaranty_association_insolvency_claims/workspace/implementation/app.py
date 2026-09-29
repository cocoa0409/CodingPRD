"""Insurance Guaranty Association & Insolvency Claims API.

A single Flask process holding every row in memory.  Nothing is seeded: a fresh
process starts with twelve empty collections and a logical clock at exactly
2026-08-01T00:00:00Z, and every row is built through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    routes.register(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_not_found(exc):
        return error_response(
            "ERR_INVALID_REQUEST", "No route matches the requested path.", 404
        )

    @app.errorhandler(405)
    def _handle_method_not_allowed(exc):
        return error_response(
            "ERR_INVALID_REQUEST", "The HTTP method is not allowed on this path.", 405
        )

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "The request is malformed.", 400)
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request could not be served.", exc.code
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        threaded=True,
        use_reloader=False,
    )
