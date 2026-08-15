"""Infusion Prior Authorization & Site-of-Care Steering API — Flask entry point."""
import os
import threading

from flask import Flask, g

from errors import ApiError, ERR_VALIDATION_FAILED
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    from routes import (
        policies, patients, auth_requests, site_determinations, benefits,
        criteria, appeals, p2p, clearances, chairs, appointments, dose_changes,
        clock,
    )
    for mod in (
        policies, patients, auth_requests, site_determinations, benefits,
        criteria, appeals, p2p, clearances, chairs, appointments, dose_changes,
        clock,
    ):
        app.register_blueprint(mod.bp)

    # Serialize requests so concurrent writers (e.g. OCC races) observe
    # check-then-act sequences atomically against the in-memory store.
    lock = threading.RLock()

    @app.before_request
    def _acquire_lock():
        lock.acquire()
        g._lock_held = True

    @app.teardown_request
    def _release_lock(exc):
        if getattr(g, "_lock_held", False):
            g._lock_held = False
            lock.release()

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        import traceback
        traceback.print_exc()
        return error_response(ERR_VALIDATION_FAILED[0], f"unexpected error: {err}",
                              ERR_VALIDATION_FAILED[1])

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
