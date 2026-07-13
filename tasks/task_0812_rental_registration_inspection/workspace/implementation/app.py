"""Rental Registration & Habitability Inspection API — Flask entry point."""
import os
from flask import Flask, jsonify

from errors import ApiError
from envelope import error_response

from routes_onboarding import bp as onboarding_bp
from routes_licenses import bp as licenses_bp
from routes_inspections import bp as inspections_bp
from routes_violations import bp as violations_bp
from routes_notices import bp as notices_bp
from routes_condemnation import bp as condemnation_bp
from routes_clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(onboarding_bp)
    app.register_blueprint(licenses_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(violations_bp)
    app.register_blueprint(notices_bp)
    app.register_blueprint(condemnation_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
