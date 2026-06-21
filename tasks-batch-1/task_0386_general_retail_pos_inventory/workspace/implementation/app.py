"""General Retail POS & Inventory API — Flask entry point.

In-memory storage only; the store starts empty on every boot. No entity is
ever seeded, preloaded, or hardcoded at startup.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.stores import bp as stores_bp
from routes.cash_sessions import bp as cash_sessions_bp
from routes.products import bp as products_bp
from routes.inventory_items import bp as inventory_items_bp
from routes.count_sheets import bp as count_sheets_bp
from routes.loyalty import bp as loyalty_bp
from routes.promotions import bp as promotions_bp
from routes.sales import bp as sales_bp
from routes.layaways import bp as layaways_bp
from routes.transfers import bp as transfers_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(stores_bp)
    app.register_blueprint(cash_sessions_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(inventory_items_bp)
    app.register_blueprint(count_sheets_bp)
    app.register_blueprint(loyalty_bp)
    app.register_blueprint(promotions_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(layaways_bp)
    app.register_blueprint(transfers_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / missing path resource -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return error_response("ERR_INVALID_REQUEST", str(exc), exc.code or 400)
        # Unexpected server error
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
