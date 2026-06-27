"""Alcohol Beverage Control API — Flask entry point.

In-memory store, logical clock, no entity seeding at startup. start.sh launches
this in the foreground binding 0.0.0.0:$PORT (default 10000)."""
import os

from flask import Flask, jsonify

import errors
from response import error_response

from routes.clock_routes import bp as clock_bp
from routes.config_routes import bp as config_bp
from routes.applications import bp as applications_bp
from routes.checks_reviews import bp as checks_bp
from routes.protests_hearings import bp as protests_bp
from routes.licenses import bp as licenses_bp
from routes.server_permits import bp as permits_bp
from routes.violations import bp as violations_bp
from routes.compliance import bp as compliance_bp
from routes.transfers import bp as transfers_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(checks_bp)
    app.register_blueprint(protests_bp)
    app.register_blueprint(licenses_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(violations_bp)
    app.register_blueprint(compliance_bp)
    app.register_blueprint(transfers_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(errors.ERR_INVALID_REQUEST, 400, "Bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, errors.ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response(errors.ERR_INVALID_REQUEST, 400, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
