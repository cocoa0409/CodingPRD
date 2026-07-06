"""Home Infusion Therapy API — Flask entry point.

In-memory storage only; the store starts EMPTY on every boot (no seeding).
Reads PORT from env, binds 0.0.0.0, runs in the foreground."""
import os

from flask import Flask, request

import errors
from response import error_response

from routes.reference import bp as reference_bp
from routes.referrals import bp as referrals_bp
from routes.infusion_orders import bp as infusion_orders_bp
from routes.prior_authorizations import bp as prior_authorizations_bp
from routes.compounds import bp as compounds_bp
from routes.supply_kits import bp as supply_kits_bp
from routes.nursing_visits import bp as nursing_visits_bp
from routes.lab_results import bp as lab_results_bp
from routes.adverse_events import bp as adverse_events_bp
from routes.claims import bp as claims_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(infusion_orders_bp)
    app.register_blueprint(prior_authorizations_bp)
    app.register_blueprint(compounds_bp)
    app.register_blueprint(supply_kits_bp)
    app.register_blueprint(nursing_visits_bp)
    app.register_blueprint(lab_results_bp)
    app.register_blueprint(adverse_events_bp)
    app.register_blueprint(claims_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route path -> ERR_NOT_FOUND envelope.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, errors.ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
