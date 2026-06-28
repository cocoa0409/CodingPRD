"""Flask entry point for the Ortho Dental Office API.

Wires every blueprint, registers the standard error envelope handlers, and runs
the server in the foreground on 0.0.0.0:$PORT (default 10000). The in-memory
store starts EMPTY on every boot — no seeding.
"""

import os

from flask import Flask

import errors
from response import error_response

from routes.clock_route import bp as clock_bp
from routes.family_accounts import bp as family_accounts_bp
from routes.patients import bp as patients_bp
from routes.providers_chairs import bp as providers_chairs_bp
from routes.growth_records import bp as growth_records_bp
from routes.insurance_policies import bp as insurance_policies_bp
from routes.treatment_plans import bp as treatment_plans_bp
from routes.contracts import bp as contracts_bp
from routes.payments import bp as payments_bp
from routes.insurance_claims import bp as insurance_claims_bp
from routes.appointments import bp as appointments_bp
from routes.retainers import bp as retainers_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(family_accounts_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(providers_chairs_bp)
    app.register_blueprint(growth_records_bp)
    app.register_blueprint(insurance_policies_bp)
    app.register_blueprint(treatment_plans_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(insurance_claims_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(retainers_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        # Method not allowed on a known path — treat as not found per envelope.
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(errors.ERR_INVALID_REQUEST, "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, errors.ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
