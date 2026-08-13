"""Indoor Vertical Farm API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError
from response import error as error_response
from routes.catalog import bp as catalog_bp
from routes.batches import bp as batches_bp
from routes.sanitation import bp as sanitation_bp
from routes.contracts import bp as contracts_bp
from routes.shipments import bp as shipments_bp
from routes.labor import bp as labor_bp
from routes.energy import bp as energy_bp
from routes.failures import bp as failures_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp, url_prefix="/farm")
    app.register_blueprint(batches_bp, url_prefix="/farm")
    app.register_blueprint(sanitation_bp, url_prefix="/farm")
    app.register_blueprint(contracts_bp, url_prefix="/farm")
    app.register_blueprint(shipments_bp, url_prefix="/farm")
    app.register_blueprint(labor_bp, url_prefix="/farm")
    app.register_blueprint(energy_bp, url_prefix="/farm")
    app.register_blueprint(failures_bp, url_prefix="/farm")

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_bad_request(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {type(e).__name__}", 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
