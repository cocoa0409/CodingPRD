"""Surgical Loaner Ops API — Flask entry point.

Mounts all route blueprints under /vendor-office and registers error
handlers that render the standard error envelope.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response, success_object
from routes import (
    vendors,
    rooms_units,
    cases,
    requests_trays,
    checkins,
    turns,
    escalations,
    passes,
    pickups,
    claims,
    penalties,
    clock,
)

app = Flask(__name__)

PREFIX = "/vendor-office"

app.register_blueprint(clock.bp, url_prefix=PREFIX)
app.register_blueprint(vendors.bp, url_prefix=PREFIX)
app.register_blueprint(rooms_units.bp, url_prefix=PREFIX)
app.register_blueprint(cases.bp, url_prefix=PREFIX)
app.register_blueprint(requests_trays.bp, url_prefix=PREFIX)
app.register_blueprint(checkins.bp, url_prefix=PREFIX)
app.register_blueprint(turns.bp, url_prefix=PREFIX)
app.register_blueprint(escalations.bp, url_prefix=PREFIX)
app.register_blueprint(passes.bp, url_prefix=PREFIX)
app.register_blueprint(pickups.bp, url_prefix=PREFIX)
app.register_blueprint(claims.bp, url_prefix=PREFIX)
app.register_blueprint(penalties.bp, url_prefix=PREFIX)


@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    # Never leak a stack trace; render the standard envelope.
    return error_response("ERR_INTERNAL", str(err), 500)


@app.get("/")
def root():
    return success_object({"service": "surgical-loaner-ops", "status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
