"""Entry point: register blueprints and error handlers; start Flask in foreground."""
from __future__ import annotations

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db  # noqa: F401  (ensure module is loaded; stores reset on boot)
import errors
import response
from routes.business_entities import bp as business_entities_bp
from routes.registered_agents import bp as registered_agents_bp
from routes.operating_agreements import bp as operating_agreements_bp
from routes.ein_applications import bp as ein_applications_bp
from routes.annual_reports import bp as annual_reports_bp
from routes.foreign_qualifications import bp as foreign_qualifications_bp
from routes.boi_disclosures import bp as boi_disclosures_bp
from routes.compliance_events import bp as compliance_events_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Disable Flask's default 404/405 HTML pages — we want JSON envelopes.
    app.url_map.strict_slashes = False

    # Blueprints
    app.register_blueprint(business_entities_bp)
    app.register_blueprint(registered_agents_bp)
    app.register_blueprint(operating_agreements_bp)
    app.register_blueprint(ein_applications_bp)
    app.register_blueprint(annual_reports_bp)
    app.register_blueprint(foreign_qualifications_bp)
    app.register_blueprint(boi_disclosures_bp)
    app.register_blueprint(compliance_events_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.APIError)
    def handle_api_error(e: errors.APIError):
        return response.error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(HTTPException)
    def handle_http(e: HTTPException):
        # 404 from Werkzeug (no route matched) -> ERR_NOT_FOUND envelope.
        # 405 (method not allowed) -> ERR_NOT_FOUND too (no concept of 405 in
        # this scaffold's error catalog; the closest is 404 / NOT_FOUND).
        if e.code == 404:
            return response.error_response(errors.ERR_NOT_FOUND, "Route not found.", 404)
        if e.code == 405:
            return response.error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 404)
        if e.code == 400:
            return response.error_response(errors.ERR_INVALID_REQUEST, e.description or "Bad request.", 400)
        # Fallback: re-wrap in our envelope with a generic error_id.
        return response.error_response(errors.ERR_INVALID_REQUEST,
                                       e.description or str(e),
                                       e.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(e: Exception):
        # Last-ditch: never leak HTML. Wrap as INVALID_REQUEST with 500.
        return response.error_response(errors.ERR_INVALID_REQUEST, f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # `use_reloader=False` so a single foreground process is spawned (the
    # harness restarts us between tests; we should not double-fork).
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
