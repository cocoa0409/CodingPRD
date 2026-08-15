"""Relocation Benefits API — Flask entry point.

Boots an empty in-memory store; no seeding. Listens on $PORT (default 10000),
binds 0.0.0.0, runs in foreground.
"""

import os

from flask import Flask, jsonify

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.employees import bp as employees_bp
from routes.policies import bp as policies_bp
from routes.vendors import bp as vendors_bp
from routes.cases import bp as cases_bp
from routes.move_assignments import bp as move_assignments_bp
from routes.service_bookings import bp as service_bookings_bp
from routes.expense_claims import bp as expense_claims_bp
from routes.home_sales import bp as home_sales_bp
from routes.repayment_agreements import bp as repayment_agreements_bp
from routes.exception_requests import bp as exception_requests_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        employees_bp, policies_bp, vendors_bp, cases_bp,
        move_assignments_bp, service_bookings_bp, expense_claims_bp,
        home_sales_bp, repayment_agreements_bp, exception_requests_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Last-resort: don't leak stack traces
        return error_response(ERR_INVALID_REQUEST, str(err) or "unexpected error", 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
