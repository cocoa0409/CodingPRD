"""D&O liability underwriting and claims API.

In-memory only: every process start begins with an empty store and a logical
clock reading 2026-08-01T00:00:00Z. Nothing is seeded and nothing is persisted.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import claims, insureds, ops, policies, quotes, submissions


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (insureds, submissions, quotes, policies, claims, ops):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "The method is not allowed for this resource.", 405
            )
        if exc.code in (400, 415):
            return error_response(
                "ERR_INVALID_REQUEST", "The request body or query string is malformed.", 422
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
