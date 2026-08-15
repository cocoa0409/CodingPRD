"""Entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response
from routes import growers, gin_shifts, modules, bales, warehouse_receipts, seed_sales, settlements, shipping_orders


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    growers.register_clock(app)
    app.register_blueprint(growers.bp)
    app.register_blueprint(gin_shifts.bp)
    app.register_blueprint(modules.bp)
    app.register_blueprint(bales.bp)
    app.register_blueprint(warehouse_receipts.bp)
    app.register_blueprint(seed_sales.bp)
    app.register_blueprint(settlements.bp)
    app.register_blueprint(shipping_orders.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        err_id, status = ERR_INVALID_REQUEST
        # Unknown path: surface as generic 404 with envelope
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(500)
    def handle_500(err):
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
