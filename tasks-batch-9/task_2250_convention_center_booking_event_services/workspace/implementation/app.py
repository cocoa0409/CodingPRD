"""Convention Center Booking & Event Services API.

A single Flask process holding every entity in memory.  Nothing is persisted and
nothing is seeded: a fresh boot exposes an empty store and a logical clock
reading exactly 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes
from errors import ApiError
from response import error_response

API_PREFIX = "/convention-center"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    routes.register(app, prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_BOOKING_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "The HTTP method is not allowed for this path.", 405
            )
        if exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
