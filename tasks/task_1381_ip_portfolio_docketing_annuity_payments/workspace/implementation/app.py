"""IP Portfolio Docketing & Annuity Payments API — Flask entry point.

All routes mount at the API root (SCAFFOLD api_prefix is ""). The store is
fully in-memory and starts empty on every boot (no seeding); the logical clock
starts at exactly 2026-08-01T00:00:00Z (PRD §2.4).
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response
import routes.ops as ops_routes
import routes.jurisdiction as jurisdiction_routes
import routes.clients as client_routes
import routes.counsel as counsel_routes
import routes.inventors as inventor_routes
import routes.families as family_routes
import routes.applications as application_routes
import routes.docket as docket_routes
import routes.annuities as annuity_routes
import routes.instructions as instruction_routes
import routes.reviews as review_routes
import routes.assignments as assignment_routes
import routes.audits as audit_routes
import routes.lists as list_routes


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        ops_routes, jurisdiction_routes, client_routes, counsel_routes,
        inventor_routes, family_routes, application_routes, docket_routes,
        annuity_routes, instruction_routes, review_routes, assignment_routes,
        audit_routes, list_routes,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response(ERR_INVALID_REQUEST, str(err), 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
