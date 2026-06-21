"""Entry point: app construction, error handlers, route registration.

In-memory storage only. NO seeding. A fresh process wipes all state.
"""
import os

from flask import Flask, request

from errors import ApiError, ERROR_STATUS
import response

from routes.catalog import bp as catalog_bp
from routes.service import bp as service_bp
from routes.sales import bp as sales_bp
from routes.holders import bp as holders_bp
from routes.builds import bp as builds_bp
from routes.misc import bp as misc_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(service_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(holders_bp)
    app.register_blueprint(builds_bp)
    app.register_blueprint(misc_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route — treat as ERR_NOT_FOUND for consistency.
        return response.error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return response.error("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return response.error(err.error_id, err.message, err.http_status)
        # Defensive fallback; should not be hit in normal operation.
        return response.error("ERR_INVALID_REQUEST", str(err), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
