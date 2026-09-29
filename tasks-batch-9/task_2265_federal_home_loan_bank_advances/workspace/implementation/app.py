"""FHLB Advances & Collateral Pledging API - Flask application entry point.

Storage is entirely in memory and starts empty on every boot.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_advance  # noqa: F401  (route registration side effect)
import routes_collateral  # noqa: F401
import routes_member  # noqa: F401
from envelope import error_response
from errors import ApiError
from routing import register_all


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        pass
    register_all(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "The HTTP method is not allowed for this path.", 405)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Bad request.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", "An unexpected server error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
