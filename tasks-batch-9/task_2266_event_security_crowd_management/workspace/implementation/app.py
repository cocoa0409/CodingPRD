"""Event Security & Crowd Management API (Flask, in-memory).

The process holds all state in plain Python dicts (see db.py). Nothing is seeded:
a fresh boot starts with every collection empty and the logical clock at
2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes
from errors import ERROR_STATUS, ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    routes.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "The HTTP method is not allowed for this resource.",
                405,
            )
        if exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request body could not be parsed as JSON.", 400
            )
        if exc.code == 415:
            return error_response(
                "ERR_INVALID_REQUEST", "The request body must be JSON.", 400
            )
        status = exc.code if isinstance(exc.code, int) else 500
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", "An unexpected server error occurred.", 500)

    return app


app = create_app()

# ERROR_STATUS is imported so the catalogue is loaded (and validated) at boot.
assert ERROR_STATUS


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
