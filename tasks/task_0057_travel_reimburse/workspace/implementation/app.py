"""Flask entry point: registers blueprints, error handlers, and starts the server."""

from __future__ import annotations

import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_NOT_FOUND, ERR_VALIDATION
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register blueprints
    from routes.employees import bp as employees_bp
    from routes.expense_standards import bp as expense_standards_bp
    from routes.travel_applications import bp as travel_apps_bp
    from routes.invoices import bp as invoices_bp
    from routes.reimbursement_forms import bp as reimb_forms_bp
    from routes.payments import bp as payments_bp
    from routes.audit import bp as audit_bp
    from routes.test_harness import bp as test_harness_bp

    app.register_blueprint(employees_bp)
    app.register_blueprint(expense_standards_bp)
    app.register_blueprint(travel_apps_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(reimb_forms_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(test_harness_bp)

    # ---------------- Error handlers ----------------
    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_VALIDATION, "Method not allowed", 422)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_VALIDATION, "Bad request", 422)

    @app.errorhandler(HTTPException)
    def handle_http(err: HTTPException):
        if err.code == 404:
            return error_response(ERR_NOT_FOUND, "Resource not found", 404)
        if err.code in (400, 405, 415):
            return error_response(ERR_VALIDATION, err.description or "Bad request", 422)
        return error_response("ERR_INTERNAL", err.description or "HTTP error", err.code or 500)

    @app.errorhandler(Exception)
    def handle_uncaught(err: Exception):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", f"Internal error: {err}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
