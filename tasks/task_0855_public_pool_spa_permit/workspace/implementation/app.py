"""Public Pool & Spa Health Permit API — Flask entry point.

Boots with a completely empty in-memory store.  No seeding of any kind.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERROR_HTTP_STATUS
from response import error_response

import routes_core
import routes_plan_permits
import routes_inspections
import routes_ops


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    routes_core.register(app)
    routes_plan_permits.register(app)
    routes_inspections.register(app)
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
        return error_response("ERR_VALIDATION", "Unexpected server error: %s" % exc,
                              500)

    @app.after_request
    def _no_keep_alive(resp):
        # werkzeug's dev server keep-alive can race the per-test server restart
        resp.headers["Connection"] = "close"
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
