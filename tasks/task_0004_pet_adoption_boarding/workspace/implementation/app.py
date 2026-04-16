import os
from flask import Flask
from errors import ApiError
from response import error_response

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(500)
def handle_500(e):
    return error_response("ERR_INTERNAL", "Internal server error", 500)


# Register blueprints
from routes.shelters import shelters_bp
from routes.animals import animals_bp
from routes.vaccination_records import vaccination_records_bp
from routes.adopters import adopters_bp
from routes.adoption_applications import applications_bp
from routes.home_visits import home_visits_bp
from routes.boarding_reservations import reservations_bp, boarding_matches_bp
from routes.fee_invoices import fee_invoices_bp
from routes.compliance_holds import compliance_holds_bp
from routes.fee_schedules import fee_schedules_bp
from routes.settlement_batches import settlement_batches_bp

app.register_blueprint(shelters_bp)
app.register_blueprint(animals_bp)
app.register_blueprint(vaccination_records_bp)
app.register_blueprint(adopters_bp)
app.register_blueprint(applications_bp)
app.register_blueprint(home_visits_bp)
app.register_blueprint(reservations_bp)
app.register_blueprint(boarding_matches_bp)
app.register_blueprint(fee_invoices_bp)
app.register_blueprint(compliance_holds_bp)
app.register_blueprint(fee_schedules_bp)
app.register_blueprint(settlement_batches_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
