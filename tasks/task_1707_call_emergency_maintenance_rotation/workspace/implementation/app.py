"""On-Call Emergency Maintenance Rotation API — entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response

app = Flask(__name__)

from routes.technicians import bp as technicians_bp
from routes.units import bp as units_bp
from routes.vendors import bp as vendors_bp
from routes.rotation_shifts import bp as rotation_shifts_bp
from routes.call_tickets import bp as call_tickets_bp
from routes.work_orders import bp as work_orders_bp
from routes.vendor_authorizations import bp as vendor_authorizations_bp
from routes.relocation_cases import bp as relocation_cases_bp
from routes.incident_records import bp as incident_records_bp
from routes.pay_periods import bp as pay_periods_bp
from routes.ops import bp as ops_bp

app.register_blueprint(technicians_bp)
app.register_blueprint(units_bp)
app.register_blueprint(vendors_bp)
app.register_blueprint(rotation_shifts_bp)
app.register_blueprint(call_tickets_bp)
app.register_blueprint(work_orders_bp)
app.register_blueprint(vendor_authorizations_bp)
app.register_blueprint(relocation_cases_bp)
app.register_blueprint(incident_records_bp)
app.register_blueprint(pay_periods_bp)
app.register_blueprint(ops_bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response(ERR_INVALID_REQUEST, "Resource or route not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response(ERR_INVALID_REQUEST, str(err), 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
