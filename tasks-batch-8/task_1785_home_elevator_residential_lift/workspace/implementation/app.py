"""Home Elevator & Residential Lift API — Flask entry point.

In-memory only: all state lives in module-level dicts in db.py and is wiped on
every process start. No disk storage, no seeding.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response
from routes import (
    catalog, certificates, change_orders, clock, contracts, grants,
    inspections, permits, projects, properties, service_calls, surveys, units,
    work_orders,
)

app = Flask(__name__)

for bp in (
    properties.bp,
    surveys.bp,
    catalog.bp,
    projects.bp,
    permits.bp,
    work_orders.bp,
    units.bp,
    inspections.bp,
    certificates.bp,
    contracts.bp,
    service_calls.bp,
    grants.bp,
    change_orders.bp,
    clock.bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(HTTPException)
def handle_http_exception(err):
    status = err.code or 500
    return error_response(ERR_INVALID_REQUEST, status, err.description or "HTTP error")


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response(ERR_INVALID_REQUEST, 500, f"Unexpected server error: {err}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
