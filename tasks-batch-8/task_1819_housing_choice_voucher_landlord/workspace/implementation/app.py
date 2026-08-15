"""Flask entry point: error handlers, route registration, app runner.

The store starts empty on every boot — no seeding, no preloading.
"""

import os

from flask import Flask

import errors
from response import error_response

from routes.landlords import bp as landlords_bp
from routes.properties import bp as properties_bp
from routes.units import bp as units_bp
from routes.voucher_families import bp as voucher_families_bp
from routes.payment_standards import bp as payment_standards_bp
from routes.rent_comparables import bp as rent_comparables_bp
from routes.contracts import bp as contracts_bp
from routes.inspections import bp as inspections_bp
from routes.repair_items import bp as repair_items_bp
from routes.rent_increase_requests import bp as rent_increase_requests_bp
from routes.recertifications import bp as recertifications_bp
from routes.hap_payments import bp as hap_payments_bp
from routes.portability_actions import bp as portability_actions_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)

    app.register_blueprint(landlords_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(units_bp)
    app.register_blueprint(voucher_families_bp)
    app.register_blueprint(payment_standards_bp)
    app.register_blueprint(rent_comparables_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(repair_items_bp)
    app.register_blueprint(rent_increase_requests_bp)
    app.register_blueprint(recertifications_bp)
    app.register_blueprint(hap_payments_bp)
    app.register_blueprint(portability_actions_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.APIError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_):
        return error_response(errors.ERR_NOT_FOUND, "Route or resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Last-ditch error mapping; should not normally fire.
        return error_response(errors.ERR_INVALID_STATE, f"Internal error: {err}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
