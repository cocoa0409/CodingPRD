"""Garden Center & Plant Nursery Retail API — entry point.

In-memory only; store starts empty on every boot (no seeding). The test harness
restarts this process before each test, wiping all state.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body

from routes.nurseries import bp as nurseries_bp
from routes.accounts import bp as accounts_bp
from routes.products import bp as products_bp
from routes.inventory_lots import bp as inventory_lots_bp
from routes.promotions import bp as promotions_bp
from routes.vehicles import bp as vehicles_bp
from routes.orders import bp as orders_bp
from routes.special_orders import bp as special_orders_bp
from routes.deliveries import bp as deliveries_bp
from routes.warranty_claims import bp as warranty_claims_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(nurseries_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(inventory_lots_bp)
    app.register_blueprint(promotions_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(special_orders_bp)
    app.register_blueprint(deliveries_bp)
    app.register_blueprint(warranty_claims_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_body(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route — not a catalogued domain error.
        return jsonify(error_body("ERR_NURSERY_NOT_FOUND", "resource not found")), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify(error_body("ERR_INVALID_REQUEST", "method not allowed")), 405

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        return jsonify(error_body("ERR_INVALID_REQUEST", str(e))), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
