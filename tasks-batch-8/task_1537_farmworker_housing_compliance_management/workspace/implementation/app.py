"""Farmworker Housing Compliance API — Flask entry point."""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response, success_object

from routes.clock_routes import bp as clock_bp
from routes.sites import bp as sites_bp
from routes.season_windows import bp as season_windows_bp
from routes.buildings import bp as buildings_bp
from routes.units import bp as units_bp
from routes.certifications import bp as certifications_bp
from routes.households import bp as households_bp
from routes.deduction_authorizations import bp as authorizations_bp
from routes.tenancies import bp as tenancies_bp
from routes.ledger import bp as ledger_bp
from routes.work_orders import bp as work_orders_bp
from routes.pest_treatments import bp as pest_treatments_bp
from routes.complaints import bp as complaints_bp
from routes.inspections import bp as inspections_bp
from routes.referrals import bp as referrals_bp

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

for bp in (
    clock_bp, sites_bp, season_windows_bp, buildings_bp, units_bp,
    certifications_bp, households_bp, authorizations_bp, tenancies_bp,
    ledger_bp, work_orders_bp, pest_treatments_bp, complaints_bp,
    inspections_bp, referrals_bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    import traceback
    traceback.print_exc()
    return error_response("ERR_INVALID_REQUEST", 400, str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
