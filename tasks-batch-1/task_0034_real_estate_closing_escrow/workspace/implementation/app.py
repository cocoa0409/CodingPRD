"""Flask entrypoint. Boots cleanly with empty in-memory state on every invocation.

Per the implementation-generator skill: no seeding / preload / hardcoded records
at startup. All entities are created through declared endpoints by the tests.
"""
from __future__ import annotations

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    err,
)
from response import error as error_response
from routes.api import bp as api_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(api_bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):  # noqa: ANN001
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(_e):  # noqa: ANN001
        return error_response(ERR_NOT_FOUND, 404, "route not found")

    @app.errorhandler(405)
    def handle_405(_e):  # noqa: ANN001
        # PRD does not enumerate a 405. The closest match in the catalog is
        # ERR_INVALID_REQUEST (422). Use that to preserve envelope shape.
        return error_response(ERR_INVALID_REQUEST, 422, "method not allowed")

    @app.errorhandler(HTTPException)
    def handle_http_exception(e: HTTPException):  # noqa: ANN001
        # Map any other werkzeug HTTPException into the envelope.
        status = e.code or 500
        if status == 401:
            return error_response(ERR_UNAUTHENTICATED, 401, e.description or "unauthenticated")
        if status == 403:
            return error_response(ERR_FORBIDDEN, 403, e.description or "forbidden")
        if status == 404:
            return error_response(ERR_NOT_FOUND, 404, e.description or "not found")
        return error_response(ERR_INVALID_REQUEST, 422, e.description or "invalid request")

    @app.errorhandler(Exception)
    def handle_generic(e: Exception):  # noqa: ANN001
        # Last-resort safety net. Avoid leaking implementation details.
        return error_response(ERR_INVALID_REQUEST, 422, "internal error")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # threaded=True so per-test-server isolation still serves concurrent requests during a single test.
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
