"""Hardware Lumber Yard API — Flask entry point.

Boots a fresh, EMPTY in-memory store on every process start (per-test-server
isolation). No seeding of any kind.
"""
import os

from flask import Flask

import errors
from response import error_response
from routes.catalog import bp as catalog_bp
from routes.accounts import bp as accounts_bp
from routes.sales import bp as sales_bp
from routes.billing_reads import bp as billing_reads_bp
from routes.rentals import bp as rentals_bp
from routes.services import bp as services_bp
from routes.special_orders import bp as special_orders_bp
from routes.purchase_orders import bp as purchase_orders_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(billing_reads_bp)
    app.register_blueprint(rentals_bp)
    app.register_blueprint(services_bp)
    app.register_blueprint(special_orders_bp)
    app.register_blueprint(purchase_orders_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route path -> ERR_NOT_FOUND envelope.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Re-raise ApiError-derived (handled above); anything else is a 500.
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
