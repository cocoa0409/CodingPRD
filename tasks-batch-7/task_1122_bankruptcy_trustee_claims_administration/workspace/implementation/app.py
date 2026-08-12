"""Bankruptcy Trustee Claims API — Flask entry point.

Registers exactly the 77 (method, path) route pairs declared in the scaffold
endpoint table. Storage is in-memory only; the store starts empty on every
boot and nothing is seeded.
"""
import os

from flask import Flask, jsonify

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_body

import routes_clock
import routes_cases
import routes_creditors
import routes_claims
import routes_objections
import routes_assets
import routes_sales
import routes_avoidance
import routes_plans
import routes_fees
import routes_reports

app = Flask(__name__)

for module in (
    routes_clock, routes_cases, routes_creditors, routes_claims,
    routes_objections, routes_assets, routes_sales, routes_avoidance,
    routes_plans, routes_fees, routes_reports,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


@app.errorhandler(404)
def handle_not_found(_err):
    return jsonify(error_body(ERR_NOT_FOUND, "The requested resource does not exist.")), 404


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return jsonify(error_body(ERR_NOT_FOUND, "The requested resource does not exist.")), 404


@app.errorhandler(400)
def handle_bad_request(_err):
    return jsonify(error_body(ERR_INVALID_REQUEST, "Malformed request.")), 400


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return jsonify(error_body(err.error_id, err.message)), err.http_status
    return jsonify(error_body(ERR_INVALID_REQUEST, str(err))), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
