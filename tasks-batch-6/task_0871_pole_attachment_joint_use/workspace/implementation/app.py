"""Pole-Attachment & Joint-Use Management API — Flask entry point.

Boots with a completely empty in-memory store.  No seeding of any kind.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

import routes_setup
import routes_app
import routes_ops


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    routes_setup.register(app)
    routes_app.register(app)
    routes_ops.register(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_VALIDATION", "Unknown route.", 404)
        if exc.code == 405:
            return error_response("ERR_VALIDATION", "Method not allowed.", 405)
        return error_response("ERR_VALIDATION", exc.description or "Bad request",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_VALIDATION", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Keep-alive is left at werkzeug's default; no Connection header is set.
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
