"""Concierge Senior Transport API — entry point.

Flask app wiring: error handlers produce the standard envelope; route modules
register their endpoints. Storage is fully in-memory (core.db) and starts
empty on every boot.
"""

import os

from flask import Flask

from core import ApiError, error_body, err_not_found, db

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_body(exc.error_id, exc.message), exc.http_status


@app.errorhandler(404)
def handle_404(exc):
    return error_body("ERR_NOT_FOUND", "Resource not found"), 404


@app.errorhandler(405)
def handle_405(exc):
    return error_body("ERR_INVALID_REQUEST", "Method not allowed"), 405


@app.errorhandler(400)
def handle_400(exc):
    return error_body("ERR_INVALID_REQUEST", "Bad request"), 400


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return error_body("ERR_INVALID_REQUEST", str(exc)), 500


import routes_clients
import routes_drivers
import routes_rates
import routes_standing
import routes_rides
import routes_assignments
import routes_billing
import routes_ops

routes_clients.register(app)
routes_drivers.register(app)
routes_rates.register(app)
routes_standing.register(app)
routes_rides.register(app)
routes_assignments.register(app)
routes_billing.register(app)
routes_ops.register(app)


@app.before_request
def _serialize_writes():
    """Serialize all requests through one re-entrant lock (single-process,
    in-memory store; protects concurrent test-driver threads)."""
    db.lock.acquire()


@app.teardown_request
def _release_lock(exc=None):
    try:
        db.lock.release()
    except RuntimeError:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
