"""Percentage Rent & Retail Sales Reporting API.

In-memory only: the store starts completely empty on every boot. No entity is
seeded, preloaded or hardcoded at startup — every precondition any client needs
is built through the declared API surface.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import routes_audit
import routes_center
import routes_charge
import routes_clause
import routes_lease
import routes_report
from core import ApiError, error_response, request_lock


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    routes_center.register(app)
    routes_lease.register(app)
    routes_report.register(app)
    routes_charge.register(app)
    routes_clause.register(app)
    routes_audit.register(app)

    @app.before_request
    def _acquire():
        request_lock.acquire()
        g._locked = True
        g._touched = set()

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_locked", False):
            g._locked = False
            try:
                request_lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_INVALID_REQUEST", 404, "Unknown resource path."))
        if err.code == 405:
            return error_response(ApiError("ERR_INVALID_REQUEST", 405, "Method not allowed."))
        return error_response(
            ApiError("ERR_INVALID_REQUEST", err.code or 400, err.description or "Request failed.")
        )

    @app.errorhandler(Exception)
    def _unhandled(err):
        app.logger.exception("unhandled error")
        return error_response(ApiError("ERR_INTERNAL", 500, str(err)))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
