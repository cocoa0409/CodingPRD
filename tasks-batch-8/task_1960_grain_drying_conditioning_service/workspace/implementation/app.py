"""Grain Drying & Conditioning API — entry point (PRD: mounted under /grain-drying)."""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import billing, blends, claims, clock, customers, lots, runs, schedules, storage, tests, tickets, units

API_PREFIX = "/grain-drying"

app = Flask(__name__)

for module in (
    customers,
    lots,
    tests,
    schedules,
    units,
    tickets,
    runs,
    blends,
    claims,
    storage,
    billing,
    clock,
):
    app.register_blueprint(module.bp, url_prefix=API_PREFIX)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", 500, "Internal server error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
