"""Nursing Licensure and Discipline Management System -- Flask entry point.

All state is held in process memory (see store.py). Nothing is seeded: every
entity is created through the declared HTTP endpoints.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import routes_core
import routes_enforcement
import routes_licensing
import routes_renewal
import store
from envelope import error
from errors import ERROR_CATALOG, ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_licensing.bp)
    app.register_blueprint(routes_renewal.bp)
    app.register_blueprint(routes_enforcement.bp)

    @app.before_request
    def _acquire():
        store.STORE.lock.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_holds_lock", False):
            g._holds_lock = False
            try:
                store.STORE.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            eid = "ERR_NOT_FOUND"
        elif exc.code == 405:
            eid = "ERR_METHOD_NOT_ALLOWED"
        elif exc.code in (400, 415):
            eid = "ERR_INVALID_REQUEST"
        else:
            eid = "ERR_INTERNAL"
        status, message = ERROR_CATALOG.get(eid, (exc.code or 500, "Request failed."))
        return error(eid, message, exc.code or status)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - safety net
        app.logger.exception("unhandled error: %s", exc)
        status, message = ERROR_CATALOG["ERR_INTERNAL"]
        return error("ERR_INTERNAL", message, status)

    return app


application = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
