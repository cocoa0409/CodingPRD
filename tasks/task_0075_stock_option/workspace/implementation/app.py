"""Stock Option Incentive API — Flask entry point."""

import os
from flask import Flask
from werkzeug.exceptions import HTTPException, NotFound, MethodNotAllowed

from errors import APIError
from response import error_response

from routes.plans import bp as plans_bp
from routes.batches import bp as batches_bp
from routes.grantees import bp as grantees_bp
from routes.grants import bp as grants_bp
from routes.windows import bp as windows_bp
from routes.corporate_events import bp as corporate_events_bp
from routes.applications import bp as applications_bp
from routes.tax_events import bp as tax_events_bp
from routes.departures import bp as departures_bp
from routes.audit_log import bp as audit_log_bp


def create_app():
    app = Flask(__name__)
    # Don't sort JSON keys for predictable output
    app.json.sort_keys = False

    # Register blueprints
    app.register_blueprint(plans_bp)
    app.register_blueprint(batches_bp)
    app.register_blueprint(grantees_bp)
    app.register_blueprint(grants_bp)
    app.register_blueprint(windows_bp)
    app.register_blueprint(corporate_events_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(tax_events_bp)
    app.register_blueprint(departures_bp)
    app.register_blueprint(audit_log_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(NotFound)
    def _handle_404(err):
        return error_response("ERR_NOT_FOUND", 404, str(err))

    @app.errorhandler(MethodNotAllowed)
    def _handle_405(err):
        return error_response("ERR_INVALID_REQUEST", 422, "Method not allowed")

    @app.errorhandler(HTTPException)
    def _handle_http_error(err):
        # Translate generic HTTP errors to our envelope
        status = err.code or 500
        if status == 404:
            return error_response("ERR_NOT_FOUND", 404, err.description or "Not found")
        if status == 400:
            return error_response("ERR_INVALID_REQUEST", 422, err.description or "Bad request")
        return error_response("ERR_INVALID_REQUEST", status if status >= 400 else 422,
                              err.description or "HTTP error")

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        # Avoid leaking stack details; map to invalid request envelope
        return error_response("ERR_INVALID_REQUEST", 500, f"Internal error: {err}")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
