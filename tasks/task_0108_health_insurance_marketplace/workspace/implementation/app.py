"""Application entry point — Flask server for the Health Insurance Marketplace API."""

import os
import traceback

from flask import Flask, jsonify

from errors import APIError
from response import error_response

from routes.application_routes import bp as applications_bp
from routes.household_routes import bp as household_bp
from routes.sep_routes import bp as sep_bp
from routes.catalog_routes import bp as catalog_bp
from routes.enrollment_routes import bp as enrollment_bp
from routes.invoice_routes import bp as invoice_bp
from routes.admin_routes import bp as admin_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register all blueprints (no url_prefix — paths are already explicit)
    app.register_blueprint(applications_bp)
    app.register_blueprint(household_bp)
    app.register_blueprint(sep_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(enrollment_bp)
    app.register_blueprint(invoice_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_bad_request(err):
        return error_response("ERR_INVALID_STATE", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_uncaught(err):
        # Don't leak details; log and respond with a server error envelope
        traceback.print_exc()
        return error_response("ERR_INVALID_STATE", str(err), 500)

    return app


flask_app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False)
