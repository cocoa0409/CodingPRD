"""Flask entry point: app factory, error handlers, route registration."""

import os

from flask import Flask, jsonify

from db import db
from errors import ApiError
from util import error_envelope


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.clock_routes import bp as clock_bp
    from routes.claim_invoices import bp as invoices_bp
    from routes.cost_lines import bp as cost_lines_bp
    from routes.damage_cases import bp as cases_bp
    from routes.disputes import bp as disputes_bp
    from routes.excavators import bp as excavators_bp
    from routes.fault_allocations import bp as allocations_bp
    from routes.locate_responses import bp as responses_bp
    from routes.locate_tickets import bp as tickets_bp
    from routes.locators import bp as locators_bp
    from routes.payments import bp as payments_bp
    from routes.regulatory_reports import bp as reports_bp
    from routes.subrogation import bp as subrogation_bp
    from routes.violations_training import bp as violations_bp

    for bp in (clock_bp, excavators_bp, locators_bp, tickets_bp, responses_bp,
               cases_bp, allocations_bp, cost_lines_bp, invoices_bp,
               payments_bp, disputes_bp, subrogation_bp, reports_bp,
               violations_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_envelope(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify(error_envelope("ERR_NOT_FOUND", "resource not found")), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify(error_envelope("ERR_NOT_FOUND", "method not allowed")), 404

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return jsonify(error_envelope(e.error_id, e.message)), e.http_status
        return jsonify(error_envelope("ERR_INVALID_REQUEST", str(e))), 400

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
