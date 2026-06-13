"""Funeral Home & Cemetery API — Flask entry point.

In-memory store, no seeding: every boot starts empty. The test harness
(`--isolation per-test-server`) restarts this process before each test.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from response import error_response

from routes.funeral_homes import bp as funeral_homes_bp
from routes.gpl_items import bp as gpl_items_bp
from routes.cases import bp as cases_bp
from routes.statement_lines import bp as statement_lines_bp
from routes.contracts import bp as contracts_bp
from routes.trust_deposits import bp as trust_deposits_bp
from routes.insurance_assignments import bp as insurance_assignments_bp
from routes.plots import bp as plots_bp
from routes.venues import bp as venues_bp
from routes.events import bp as events_bp
from routes.permits import bp as permits_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(funeral_homes_bp)
    app.register_blueprint(gpl_items_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(statement_lines_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(trust_deposits_bp)
    app.register_blueprint(insurance_assignments_bp)
    app.register_blueprint(plots_bp)
    app.register_blueprint(venues_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(permits_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Map any other HTTP exception into the standard error envelope.
        status = exc.code or 500
        if status == 400:
            return error_response(errors.ERR_INVALID_REQUEST, "Bad request", 422)
        return error_response("ERR_INTERNAL", exc.description or "Error", status)

    @app.errorhandler(Exception)
    def handle_unexpected(_exc):
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
