"""Upholstery & Furniture Refinishing API — entry point.

In-memory only. Every boot starts with an empty store (no seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.customers import bp as customers_bp
from routes.catalog import bp as catalog_bp
from routes.work_orders import bp as work_orders_bp
from routes.estimates import bp as estimates_bp
from routes.workflow import bp as workflow_bp
from routes.materials import bp as materials_bp
from routes.scheduling import bp as scheduling_bp
from routes.warranty import bp as warranty_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(estimates_bp)
    app.register_blueprint(workflow_bp)
    app.register_blueprint(materials_bp)
    app.register_blueprint(scheduling_bp)
    app.register_blueprint(warranty_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route / path. Treated as a resource-not-found style miss.
        return error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_RESOURCE_NOT_FOUND",
                              "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, HTTPException):
            return error_response("ERR_INVALID_REQUEST", str(e), e.code or 400)
        return error_response("ERR_INVALID_REQUEST", "Internal error", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
