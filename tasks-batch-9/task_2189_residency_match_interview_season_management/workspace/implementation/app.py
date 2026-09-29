"""Residency Match Season API — application entry point.

The process starts with an empty store and the logical clock at
2026-08-01T00:00:00Z, so a fresh boot before every test is deterministic.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError, DEFAULT_MESSAGE, ERROR_STATUS
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_RESOURCE_NOT_FOUND",
                DEFAULT_MESSAGE["ERR_RESOURCE_NOT_FOUND"],
                404,
            )
        if exc.code == 405:
            return error_response(
                "ERR_VALIDATION", "The HTTP method is not allowed for this path.", 422
            )
        if exc.code and 400 <= exc.code < 500:
            return error_response("ERR_VALIDATION", exc.description, 422)
        return error_response(
            "ERR_INTERNAL", exc.description, ERROR_STATUS.get("ERR_INTERNAL", 500)
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", str(exc) or "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
