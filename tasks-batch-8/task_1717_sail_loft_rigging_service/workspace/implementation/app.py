"""Flask entry point — Sail Loft & Rigging Service API."""

import os

from flask import Flask, jsonify

import errors as err
from response import error_response
from routes import (
    boats,
    class_certificates,
    cloth_ledger,
    customers,
    mast_service_events,
    measurement_sheets,
    production_jobs,
    rigging_inspections,
    sail_designs,
    storage_contracts,
    work_orders,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (
    customers.bp,
    boats.bp,
    measurement_sheets.bp,
    sail_designs.bp,
    work_orders.bp,
    production_jobs.bp,
    cloth_ledger.bp,
    rigging_inspections.bp,
    mast_service_events.bp,
    storage_contracts.bp,
    class_certificates.bp,
):
    app.register_blueprint(bp)


@app.errorhandler(err.ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(err.ERR_RESOURCE_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(err.ERR_INVALID_REQUEST, "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, err.ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response(err.ERR_INVALID_REQUEST, str(e), 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
