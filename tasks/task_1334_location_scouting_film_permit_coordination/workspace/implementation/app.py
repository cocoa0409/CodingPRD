"""Main Flask application entry point."""

import os
import sys

# Ensure the implementation directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from errors import ApiError
from response import error_response

app = Flask(__name__)

# Register error handler for ApiError
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(500)
def handle_internal_error(e):
    return error_response("ERR_INVALID_REQUEST", str(e), 500)


# Register blueprints
from routes.clock_ops import bp as clock_ops_bp
from routes.jurisdictions import bp as jurisdictions_bp
from routes.owners import bp as owners_bp
from routes.locations import bp as locations_bp
from routes.productions import bp as productions_bp
from routes.location_bookings import bp as bookings_bp
from routes.scout_packages import bp as scout_packages_bp
from routes.owner_agreements import bp as owner_agreements_bp
from routes.permit_applications import bp as permit_applications_bp
from routes.street_closures import bp as street_closures_bp
from routes.notifications import bp as notifications_bp
from routes.insurance import bp as insurance_bp
from routes.deposits import bp as deposits_bp
from routes.walkthroughs import bp as walkthroughs_bp
from routes.monitors import bp as monitors_bp
from routes.shoot_days import bp as shoot_days_bp
from routes.complaints import bp as complaints_bp
from routes.cross_scope import bp as cross_scope_bp

app.register_blueprint(clock_ops_bp)
app.register_blueprint(jurisdictions_bp)
app.register_blueprint(owners_bp)
app.register_blueprint(locations_bp)
app.register_blueprint(productions_bp)
app.register_blueprint(bookings_bp)
app.register_blueprint(scout_packages_bp)
app.register_blueprint(owner_agreements_bp)
app.register_blueprint(permit_applications_bp)
app.register_blueprint(street_closures_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(insurance_bp)
app.register_blueprint(deposits_bp)
app.register_blueprint(walkthroughs_bp)
app.register_blueprint(monitors_bp)
app.register_blueprint(shoot_days_bp)
app.register_blueprint(complaints_bp)
app.register_blueprint(cross_scope_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
