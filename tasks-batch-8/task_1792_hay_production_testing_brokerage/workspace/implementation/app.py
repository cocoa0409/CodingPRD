"""Hay Brokerage API — Flask entry point.

In-memory only; the store starts empty on every boot. Reads PORT (default
10000), binds 0.0.0.0, runs in the foreground.
"""

import os
import threading

from flask import Flask, g

from errors import ApiError, ERR_INVALID_REQUEST
from response import error

import routes_admin
import routes_parties
import routes_fields
import routes_inventory
import routes_trade
import routes_logistics
import routes_baling

app = Flask(__name__)

# Serialize request handling: the in-memory store is shared mutable state.
_lock = threading.RLock()


@app.before_request
def _acquire_lock():
    _lock.acquire()
    g._hay_lock_held = True


@app.teardown_request
def _release_lock(exc=None):
    if getattr(g, "_hay_lock_held", False):
        g._hay_lock_held = False
        _lock.release()


app.register_blueprint(routes_admin.bp)
app.register_blueprint(routes_parties.bp)
app.register_blueprint(routes_fields.bp)
app.register_blueprint(routes_inventory.bp)
app.register_blueprint(routes_trade.bp)
app.register_blueprint(routes_logistics.bp)
app.register_blueprint(routes_baling.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.message, e.status)


@app.errorhandler(404)
def handle_not_found(e):
    return error("ERR_NOT_FOUND", "the requested path does not exist", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error("ERR_METHOD_NOT_ALLOWED", "method not allowed on this path", 405)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error(e.error_id, e.message, e.status)
    return error(ERR_INVALID_REQUEST, f"unhandled error: {e}", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
