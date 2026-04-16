"""Entry point for Pet Adoption Boarding API."""

import os
from flask import Flask
from errors import ApiError
from response import error_response

app = Flask(__name__)

# Register blueprints
from routes.shelters import bp as shelters_bp
from routes.animals import bp as animals_bp
from routes.vaccination_records import bp as vaccination_records_bp
from routes.adopters import bp as adopters_bp
from routes.adoption_applications import bp as adoption_applications_bp
from routes.home_visits import bp as home_visits_bp
from routes.boarding_reservations import bp as boarding_reservations_bp
from routes.fee_invoices import bp as fee_invoices_bp
from routes.compliance_holds import bp as compliance_holds_bp
from routes.fee_schedules import bp as fee_schedules_bp
from routes.boarding_matches import bp as boarding_matches_bp

app.register_blueprint(shelters_bp)
app.register_blueprint(animals_bp)
app.register_blueprint(vaccination_records_bp)
app.register_blueprint(adopters_bp)
app.register_blueprint(adoption_applications_bp)
app.register_blueprint(home_visits_bp)
app.register_blueprint(boarding_reservations_bp)
app.register_blueprint(fee_invoices_bp)
app.register_blueprint(compliance_holds_bp)
app.register_blueprint(fee_schedules_bp)
app.register_blueprint(boarding_matches_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response("ERR_NOT_FOUND", "Not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(500)
def handle_internal_error(e):
    return error_response("ERR_INTERNAL", str(e), 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
