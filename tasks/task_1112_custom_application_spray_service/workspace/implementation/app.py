"""Custom Spray Service API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). Store starts empty on every boot; the logical
clock starts at 2026-05-01T00:00:00Z. Auth (X-User-ID + X-User-Role) is enforced for
every /api/* request before routing, per the §2.9 precedence order.
"""

import os

from flask import Flask, request

from store import store
from util import ApiError, error_response, auth_context

import routes_registry
import routes_rx
import routes_people
import routes_work
import routes_records
import routes_compliance


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _lock_and_authenticate():
        store.lock.acquire()
        try:
            if request.path.startswith("/api"):
                auth_context()  # raises ERR_UNAUTHENTICATED (401)
        except Exception:
            store.lock.release()
            raise

    @app.teardown_request
    def _unlock(exc=None):
        try:
            store.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response(ApiError("ERR_NOT_FOUND", "resource not found", 404))

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response(ApiError("ERR_NOT_FOUND", "method not allowed", 405))

    @app.errorhandler(Exception)
    def _unhandled(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return error_response(ApiError("ERR_INTERNAL", str(e), 500))

    for module in (routes_registry, routes_rx, routes_people,
                   routes_work, routes_records, routes_compliance):
        app.register_blueprint(module.bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
