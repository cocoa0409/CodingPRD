"""Entry point: Flask app, error handlers, blueprint registration.

In-memory only; nothing is seeded at boot. start.sh runs `python3 app.py` in the
foreground, binding 0.0.0.0:$PORT (default 10000).
"""
import os

from flask import Flask

from errors import APIError, ERROR_CATALOG
import response

from routes.customers import bp as customers_bp
from routes.products import bp as products_bp
from routes.orders import bp as orders_bp
from routes.order_lines import bp as order_lines_bp
from routes.financing import bp as financing_bp
from routes.delivery_routes import bp as delivery_routes_bp
from routes.delivery_stops import bp as delivery_stops_bp
from routes.protection_plans import bp as protection_plans_bp
from routes.return_requests import bp as return_requests_bp
from routes.clock_admin import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(order_lines_bp)
    app.register_blueprint(financing_bp)
    app.register_blueprint(delivery_routes_bp)
    app.register_blueprint(delivery_stops_bp)
    app.register_blueprint(protection_plans_bp)
    app.register_blueprint(return_requests_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(APIError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        return response.error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, APIError):
            return response.error_response(exc.error_id, exc.http_status, exc.message)
        return response.error_response("ERR_INVALID_REQUEST", 422, "Unexpected error: %s" % exc)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
