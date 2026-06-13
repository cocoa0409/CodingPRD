"""Roadside Assistance Dispatch API — Flask entry point.

In-memory storage only; the store starts empty on every boot. No seeding.
"""
import os

from flask import Flask, request

import errors
from response import error_response
from routes.plans import bp as plans_bp
from routes.members import bp as members_bp
from routes.providers import bp as providers_bp
from routes.depots import bp as depots_bp
from routes.service_calls import bp as service_calls_bp
from routes.claims import bp as claims_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(plans_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(depots_bp)
    app.register_blueprint(service_calls_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / method — surface as a not-found error envelope.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
