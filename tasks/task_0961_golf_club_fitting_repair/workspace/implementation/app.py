"""Golf Club Fitting & Repair API — Flask entry point."""
import os

from flask import Flask

from db import db
from errors import ApiError
from response import error_response
from routes import (
    customers, staff, bays, sessions, packages, specs, items, tickets,
    appraisals, listings, claims, clock,
)

app = Flask(__name__)

PREFIX = "/golf-shop"

for module in (customers, staff, bays, sessions, packages, specs, items,
               tickets, appraisals, listings, claims, clock):
    app.register_blueprint(module.bp, url_prefix=PREFIX)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response("ERR_VALIDATION", "route not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response("ERR_VALIDATION", "method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response("ERR_VALIDATION", str(err), 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
