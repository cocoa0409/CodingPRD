"""Aircraft Brokerage Pre-Buy API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store starts empty on every boot;
per-test-server isolation re-launches this process before every test.
"""
import os
import threading

from flask import Flask

from errors import ApiError
from response import error_response

_REQUEST_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import (
        bookings,
        buyers,
        comps,
        discrepancies,
        escrow,
        facilities,
        listings,
        lois,
        transactions,
    )

    for module in (
        facilities,
        listings,
        buyers,
        comps,
        lois,
        transactions,
        escrow,
        bookings,
        discrepancies,
    ):
        app.register_blueprint(module.bp)

    @app.before_request
    def _acquire_lock():
        # Serializes mutations so OCC rejections stay deterministic even if
        # the dev server dispatches requests concurrently.
        _REQUEST_LOCK.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            _REQUEST_LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _handle_not_found(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def _handle_method_not_allowed(err):
        return error_response(
            "ERR_METHOD_NOT_ALLOWED", "method not allowed", 405
        )

    @app.errorhandler(Exception)
    def _handle_unhandled(err):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
