"""Flask entry point: error handlers, blueprint registration, server boot."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from response import error_response

from routes import (
    union_agreements, productions, performers, engagements, timecards,
    penalty_assessments, residual_obligations, pay_batches,
    garnishment_orders, remittance_reports, grievance_cases,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(union_agreements.bp)
    app.register_blueprint(productions.bp)
    app.register_blueprint(performers.bp)
    app.register_blueprint(engagements.bp)
    app.register_blueprint(timecards.bp)
    app.register_blueprint(penalty_assessments.bp)
    app.register_blueprint(residual_obligations.bp)
    app.register_blueprint(pay_batches.bp)
    app.register_blueprint(garnishment_orders.bp)
    app.register_blueprint(remittance_reports.bp)
    app.register_blueprint(grievance_cases.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response(ERR_VALIDATION, "Method not allowed", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        # Never leak a bare 500 HTML page; surface as a generic validation error.
        return error_response(ERR_VALIDATION, f"Unexpected error: {err}", 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
