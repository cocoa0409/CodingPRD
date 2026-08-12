"""Entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask

import errors as err
from errors import APIError
from response import error_response

from routes.customers import bp as customers_bp
from routes.products import bp as products_bp
from routes.area_restrictions import bp as area_restrictions_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.delivery_routes import bp as delivery_routes_bp
from routes.delivery_windows import bp as delivery_windows_bp
from routes.orders import bp as orders_bp
from routes.moisture import bp as moisture_bp
from routes.invoices import bp as invoices_bp
from routes.system_ops import bp as system_ops_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        customers_bp,
        products_bp,
        area_restrictions_bp,
        subscriptions_bp,
        delivery_routes_bp,
        delivery_windows_bp,
        orders_bp,
        moisture_bp,
        invoices_bp,
        system_ops_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        import traceback
        traceback.print_exc()
        return error_response(err.ERR_VALIDATION, f"Unexpected error: {e}", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
