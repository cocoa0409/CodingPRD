"""Commercial Fishing Quota API — Flask entry point.

In-memory only; the store starts empty on every boot. The logical clock
starts at 2026-08-01T00:00:00Z and is driven via POST /_clock/set_current_utc.
"""

import os

from flask import Flask

from errors import ApiError
from common import error_response
import store

import routes_admin
import routes_trips
import routes_transfers
import routes_observers
import routes_settlements
import routes_ops


def create_app():
    app = Flask(__name__)

    app.register_blueprint(routes_admin.bp)
    app.register_blueprint(routes_trips.bp)
    app.register_blueprint(routes_transfers.bp)
    app.register_blueprint(routes_observers.bp)
    app.register_blueprint(routes_settlements.bp)
    app.register_blueprint(routes_ops.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        wrapped = ApiError(500, "ERR_INTERNAL", str(err))
        return error_response(wrapped)

    # Serialize all requests through one lock so multi-step cascades are atomic.
    @app.before_request
    def _acquire_lock():
        store.db.lock.acquire()

    @app.teardown_request
    def _release_lock(exc):
        store.db.lock.release()

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
