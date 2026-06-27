"""Pet Store & Aquatics Supply API — entry point and error handling."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.stores import bp as stores_bp
from routes.products import bp as products_bp
from routes.inventory_lots import bp as inventory_lots_bp
from routes.livestock import bp as livestock_bp
from routes.customers import bp as customers_bp
from routes.prescriptions import bp as prescriptions_bp
from routes.clinic import bp as clinic_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.special_orders import bp as special_orders_bp
from routes.product_sales import bp as product_sales_bp
from routes.recalls import bp as recalls_bp
from routes.adoption import bp as adoption_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        stores_bp, products_bp, inventory_lots_bp, livestock_bp, customers_bp,
        prescriptions_bp, clinic_bp, subscriptions_bp, special_orders_bp,
        product_sales_bp, recalls_bp, adoption_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unmatched route — emit the envelope shape with a generic not-found.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exc(exc):
        return error_response("ERR_HTTP", exc.description or "HTTP error.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
