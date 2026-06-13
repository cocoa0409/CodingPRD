"""Audiology & Hearing Aid Clinic API — Flask entry point.

Boots a fresh, empty in-memory store on every process start (no seeding).
Registers all route blueprints and the global error handlers that render the
PRD §2.2 error envelope.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.patients import bp as patients_bp
from routes.device_models import bp as device_models_bp
from routes.allowance_benefits import bp as allowance_benefits_bp
from routes.evaluations import bp as evaluations_bp
from routes.orders import bp as orders_bp
from routes.warranty_claims import bp as warranty_claims_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.recalls import bp as recalls_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(patients_bp)
    app.register_blueprint(device_models_bp)
    app.register_blueprint(allowance_benefits_bp)
    app.register_blueprint(evaluations_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(warranty_claims_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(recalls_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unmatched route -> treat as resource not found.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        # Fall back to the error envelope for any other werkzeug HTTP error.
        return error_response("ERR_INVALID_REQUEST", err.description or "Request error.",
                              err.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Last-resort guard; never leak a stack trace as a bare 500 page.
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
