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
    return error_response("ERR_VALIDATION", "No such route.", 400)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_VALIDATION", "Method not allowed.", 400)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_VALIDATION", str(e), 400)


from routes.landlords import landlords_bp
from routes.renters import renters_bp
from routes.properties import properties_bp
from routes.renter_enrollments import renter_enrollments_bp
from routes.policies import policies_bp
from routes.invoices import invoices_bp
from routes.billing import billing_bp
from routes.claims import claims_bp
from routes.payouts import payouts_bp
from routes.subrogation import subrogation_bp
from routes.recovery_payments import recovery_payments_bp
from routes.state_compliance_rules import state_rules_bp
from routes.clock import clock_bp

app.register_blueprint(landlords_bp)
app.register_blueprint(renters_bp)
app.register_blueprint(properties_bp)
app.register_blueprint(renter_enrollments_bp)
app.register_blueprint(policies_bp)
app.register_blueprint(invoices_bp)
app.register_blueprint(billing_bp)
app.register_blueprint(claims_bp)
app.register_blueprint(payouts_bp)
app.register_blueprint(subrogation_bp)
app.register_blueprint(recovery_payments_bp)
app.register_blueprint(state_rules_bp)
app.register_blueprint(clock_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
