"""Abrasives & Industrial Consumables Program API — Flask entry point."""
import os
import threading

from flask import Flask, g

from errors import ApiError
from response import error_response

# All requests are serialized through one lock: the store is in-memory and every
# mutation + cascade must be atomic within its request (PRD 2.9).
REQUEST_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)

    from routes import (
        blanket_orders, clock, contracts, disposal_records, lots, machines,
        products, releases, standards, trials, usage_records,
    )
    for mod in (
        products, machines, lots, standards, usage_records, contracts,
        blanket_orders, releases, trials, disposal_records, clock,
    ):
        app.register_blueprint(mod.bp)

    @app.before_request
    def _acquire_lock():
        REQUEST_LOCK.acquire()
        g._lock_held = True

    @app.teardown_request
    def _release_lock(exc):
        if getattr(g, "_lock_held", False):
            g._lock_held = False
            REQUEST_LOCK.release()

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
