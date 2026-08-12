"""School Furniture Public Bid Fulfillment API — Flask entry point.

The store starts empty on every boot; every entity is constructed through the
declared API surface. All date-sensitive logic reads the logical clock.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from db import lock
from errors import ApiError, ERR_NOT_FOUND, raise_err
from response import error_response, success
from routes import (
    awards,
    backorder_notices,
    bid_specs,
    clock,
    coop_agreements,
    crews,
    damage_reports,
    districts,
    install_tasks,
    po_lines,
    purchase_orders,
    school_sites,
    shipments,
    spec_lines,
    warranty_claims,
)

app = Flask(__name__)

for module in (
    clock,
    districts,
    school_sites,
    bid_specs,
    spec_lines,
    coop_agreements,
    awards,
    purchase_orders,
    po_lines,
    shipments,
    crews,
    install_tasks,
    damage_reports,
    backorder_notices,
    warranty_claims,
):
    app.register_blueprint(module.bp)


# Serialize request handling so multi-step cascades stay atomic.
@app.before_request
def _acquire_lock():
    lock.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(err):
    return error_response(ApiError(ERR_NOT_FOUND[0], 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(err):
    return error_response(ApiError(ERR_NOT_FOUND[0], 405, "Method not allowed"))


@app.errorhandler(Exception)
def _handle_exception(err):
    if isinstance(err, ApiError):
        return error_response(err)
    if isinstance(err, HTTPException):
        return error_response(ApiError(ERR_NOT_FOUND[0], err.code, err.name))
    return error_response(ApiError("ERR_INTERNAL", 500, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
