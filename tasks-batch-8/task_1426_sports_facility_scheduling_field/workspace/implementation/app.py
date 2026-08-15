"""Entry point: Flask app, error handlers, route registration."""

import os
from flask import Flask

import errors
from response import error_response

from routes.organizations import bp as organizations_bp
from routes.facilities import bp as facilities_bp
from routes.fee_schedules import bp as fee_schedules_bp
from routes.allocation_windows import bp as allocation_windows_bp
from routes.applications import bp as applications_bp
from routes.permits import bp as permits_bp
from routes.closures import bp as closures_bp
from routes.invoices import bp as invoices_bp
from routes.payments import bp as payments_bp
from routes.strikes import bp as strikes_bp
from routes.ledgers import bp as ledgers_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        organizations_bp, facilities_bp, fee_schedules_bp, allocation_windows_bp,
        applications_bp, permits_bp, closures_bp, invoices_bp, payments_bp,
        strikes_bp, ledgers_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(errors.ERR_INVALID_REQUEST, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(errors.ERR_INVALID_REQUEST, "Method not allowed", 400)

    @app.errorhandler(500)
    def handle_500(err):
        return error_response(errors.ERR_INVALID_REQUEST, "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, use_reloader=False)
