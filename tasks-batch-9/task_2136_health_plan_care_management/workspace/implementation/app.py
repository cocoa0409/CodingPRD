"""Health Plan Care Management API — entry point.

The in-memory store starts EMPTY on every boot: no seeding, no preloading,
no persistence of any kind. Every entity is created by callers through the
declared endpoints.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import core
import http_util as h
from errors import ApiError

import routes_careplan
import routes_enrollment
import routes_member
import routes_program
import routes_social
import routes_touch

API_PREFIX = "/care-management"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (routes_member, routes_program, routes_enrollment,
                   routes_careplan, routes_touch, routes_social):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.before_request
    def _acquire():
        core.LOCK.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_holds_lock", False):
            g._holds_lock = False
            try:
                core.LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return h.error_response(exc)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return h.error_response(ApiError("ERR_NOT_FOUND", "Resource not found."))
        if exc.code == 405:
            return h.error_response(
                ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed."))
        if exc.code == 400:
            return h.error_response(
                ApiError("ERR_INVALID_REQUEST", "Malformed request."))
        return h.error_response(
            ApiError("ERR_INVALID_REQUEST", exc.description or "Request failed."))

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error")
        return h.error_response(
            ApiError("ERR_INVALID_REQUEST", "Internal error: %s" % exc))

    @app.get("/health")
    def _health():
        return h.ok({"status": "ok"})

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
