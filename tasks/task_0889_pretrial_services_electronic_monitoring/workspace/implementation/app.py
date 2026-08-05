"""Pretrial Services & Electronic Monitoring API — Flask entry point.

Boots with a completely empty in-memory store.  No seeding of any kind — every
entity a test needs is built through the declared API surface.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes
from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    routes.register(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Unknown route.", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_STATE", "Method not allowed.", 405)
        return error_response("ERR_VALIDATION", exc.description or "Bad request",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_VALIDATION",
                              "Unexpected server error: %s" % exc, 500)

    @app.after_request
    def _no_keep_alive(resp):
        # werkzeug's dev-server keep-alive can race the per-test server restart.
        resp.headers["Connection"] = "close"
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
