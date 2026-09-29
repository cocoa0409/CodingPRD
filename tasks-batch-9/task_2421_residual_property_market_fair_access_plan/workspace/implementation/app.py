"""Residual Property Fair Access Plan API.

A single Flask process holding every record in memory.  Nothing is persisted and
nothing is seeded: a fresh boot starts with an empty store and a logical clock
reading exactly 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes
from errors import ApiError
from response import error


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    routes.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "Resource not found", 404)
        return error("ERR_INVALID_REQUEST", exc.description or "Invalid request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True,
            debug=False, use_reloader=False)
