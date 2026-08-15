"""Team Travel Charter API — Flask entry point.

In-memory only; store starts empty on every boot (per-test-server isolation).
"""
import os

from flask import Flask, request

import util
from envelope import error_body
from state import ApiError
import routes_core
import routes_charter
import routes_hotel
import routes_ops
import routes_flat

app = Flask(__name__)


@app.before_request
def _gate():
    if not request.path.startswith("/travel"):
        return None
    # Time-driven transitions are evaluated against the logical clock.
    util.sweep_clock()
    # Priority 1: user-context headers on every /travel endpoint.
    util.authenticate()
    return None


@app.errorhandler(ApiError)
def _api_error(e):
    return error_body(e)


@app.errorhandler(404)
def _not_found(e):
    return error_body(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _method_not_allowed(e):
    return error_body(ApiError("ERR_INVALID_REQUEST", 405, "Method not allowed"))


@app.errorhandler(500)
def _internal(e):
    return error_body(ApiError("ERR_INVALID_REQUEST", 500, "Internal error"))


app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_charter.bp)
app.register_blueprint(routes_hotel.bp)
app.register_blueprint(routes_ops.bp)
app.register_blueprint(routes_flat.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
