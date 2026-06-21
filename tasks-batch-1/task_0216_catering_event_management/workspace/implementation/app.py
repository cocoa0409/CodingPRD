"""Catering Event Management API — Flask entry point.

In-memory storage only; the store is wiped on every process boot. No entity
seeding at startup — every entity is created by tests through the declared
API surface.
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response

from routes.catalog import bp as catalog_bp
from routes.orders import bp as orders_bp
from routes.legs import bp as legs_bp
from routes.change_requests import bp as change_requests_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(legs_bp)
    app.register_blueprint(change_requests_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route — surface as the catalogue's not-found error.
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", "internal error: %s" % e, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
