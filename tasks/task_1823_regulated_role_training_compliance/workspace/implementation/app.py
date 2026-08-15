"""Regulated Role Training Compliance API — Flask entry point.

All endpoints are mounted under /compliance. The store starts empty on every
boot; the logical clock defaults to 2026-08-01T00:00:00Z and never falls back
to wall-clock time.
"""
import os

from flask import Flask, g

from db import store
from errors import ApiError
from response import error_body
from routes import admin, assignments, attestations, ops, people, reports


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    # Serialize request handling: in-memory store with immediate consistency.
    @app.before_request
    def _acquire_store_lock():
        store.lock.acquire()
        g._store_lock_held = True

    @app.teardown_request
    def _release_store_lock(exc=None):
        if g.pop("_store_lock_held", False):
            store.lock.release()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_body(err)

    @app.errorhandler(404)
    def _not_found(err):
        return error_body(ApiError("ERR_NOT_FOUND", "resource not found"))

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_body(ApiError("ERR_NOT_FOUND", "method not allowed"))

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_body(err)
        return error_body(ApiError("ERR_INVALID_REQUEST", "unhandled error: %s" % err)), 500

    for module in (admin, people, assignments, attestations, reports, ops):
        app.register_blueprint(module.bp, url_prefix="/compliance")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
