"""Retail Co-Tenancy & Exclusive Use Administration API.

Storage is in-memory only and nothing is seeded: a fresh process starts with
zero records and the logical clock pinned to 2026-08-01T00:00:00Z.
"""
import os
import threading

from flask import Flask, g

from errors import CATALOG, ApiError
from response import error
from routes import register_routes

_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    register_routes(app)

    @app.before_request
    def _acquire():
        _LOCK.acquire()
        g._locked = True

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_locked", False):
            g._locked = False
            try:
                _LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return error("ERR_NOT_FOUND", "Method not allowed for this path", 404)

    @app.errorhandler(400)
    def _bad_request(exc):
        return error("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message,
                         CATALOG.get(exc.error_id, 400))
        return error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
