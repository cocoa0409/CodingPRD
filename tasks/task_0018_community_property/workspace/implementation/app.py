"""Community Property Management API — Flask entry point.

Boots the application, registers every blueprint under the /communities prefix,
and installs error handlers that translate APIError and 4xx framework errors
into the response envelope mandated by PRD §2.2.
"""
from __future__ import annotations

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import (
    APIError,
    ERR_AUTH_MISSING,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
)
from response import error as error_response

# Route blueprints
from routes.owners import bp as owners_bp
from routes.properties import bp as properties_bp
from routes.residents import bp as residents_bp
from routes.work_orders import bp as work_orders_bp
from routes.fee_billing_rules import bp as fee_billing_rules_bp
from routes.fee_bills import bp as fee_bills_bp
from routes.payments import bp as payments_bp
from routes.facilities import bp as facilities_bp
from routes.reservations import bp as reservations_bp
from routes.proposals import bp as proposals_bp
from routes.parking import bp as parking_bp
from routes.audit import bp as audit_bp
from routes.test_drive import bp as test_drive_bp


API_PREFIX = "/communities"


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints — every endpoint lives under /communities/...
    for bp in (
        owners_bp, properties_bp, residents_bp, work_orders_bp,
        fee_billing_rules_bp, fee_bills_bp, payments_bp,
        facilities_bp, reservations_bp, proposals_bp, parking_bp,
        audit_bp, test_drive_bp,
    ):
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    # ------------------------------------------------------------------
    # Error handlers — every error path produces the §2.2 error envelope.
    # ------------------------------------------------------------------
    @app.errorhandler(APIError)
    def _handle_api_error(err: APIError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _handle_404(err):
        return error_response(ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def _handle_405(err):
        return error_response(
            ERR_VALIDATION, "Method not allowed for this endpoint.", 405
        )

    @app.errorhandler(400)
    def _handle_400(err):
        msg = getattr(err, "description", "Bad request")
        return error_response(ERR_VALIDATION, msg, 400)

    @app.errorhandler(415)
    def _handle_415(err):
        return error_response(ERR_VALIDATION, "Unsupported media type.", 415)

    @app.errorhandler(HTTPException)
    def _handle_http(err: HTTPException):
        # Authoritative fallback for any other HTTPException Flask might raise.
        return error_response(
            ERR_VALIDATION, err.description or err.name, err.code or 500
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception):
        # Last-resort handler — never let raw 500s leak HTML.
        return error_response("ERR_INTERNAL", str(err) or "Internal server error.", 500)

    @app.get("/health")
    def health():
        # Health endpoint is unauthenticated and outside the API envelope.
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
