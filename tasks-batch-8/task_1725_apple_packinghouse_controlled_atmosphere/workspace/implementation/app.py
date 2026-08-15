"""Apple Packinghouse & Controlled-Atmosphere Storage API — Flask entry point."""
import os
import threading

from flask import Flask, g

from errors import ApiError
from response import error_response

STORE_LOCK = threading.Lock()


def create_app():
    app = Flask(__name__)
    try:
        app.json.sort_keys = False
    except Exception:
        pass

    from routes import (
        growers, lots, rooms, allocations, specs, runs, pools, settlements, clock,
    )
    for mod in (
        growers, lots, rooms, allocations, specs, runs, pools, settlements, clock,
    ):
        app.register_blueprint(mod.bp)

    @app.before_request
    def _acquire_store_lock():
        # Serialize requests so cascades stay atomic under concurrent clients.
        STORE_LOCK.acquire()
        g._store_lock_held = True

    @app.teardown_request
    def _release_store_lock(exc):
        if getattr(g, "_store_lock_held", False):
            g._store_lock_held = False
            STORE_LOCK.release()

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
        return error_response("ERR_INVALID_REQUEST", f"unexpected error: {err}", 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
