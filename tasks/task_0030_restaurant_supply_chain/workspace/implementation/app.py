"""Restaurant Supply Chain API — Flask entry point.

Implements the REST API described in PRD.md / SCAFFOLD.yaml. The server listens
on the PORT env var (default 10000), bound to 0.0.0.0.
"""

import os

from flask import Flask, jsonify

import db
import errors
import response
from routes.stores import bp as stores_bp
from routes.recipes import bp as recipes_bp
from routes.ingredients import bp as ingredients_bp
from routes.store_orders import bp as store_orders_bp
from routes.production_batches import bp as production_batches_bp
from routes.vehicles import bp as vehicles_bp
from routes.delivery_routes import bp as delivery_routes_bp
from routes.inventory_batches import bp as inventory_batches_bp
from routes.replenishment_rules import bp as replenishment_rules_bp
from routes.loss_records import bp as loss_records_bp
from routes.cost_allocations import bp as cost_allocations_bp
from routes.audit_log import bp as audit_log_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(stores_bp)
    app.register_blueprint(recipes_bp)
    app.register_blueprint(ingredients_bp)
    app.register_blueprint(store_orders_bp)
    app.register_blueprint(production_batches_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(delivery_routes_bp)
    app.register_blueprint(inventory_batches_bp)
    app.register_blueprint(replenishment_rules_bp)
    app.register_blueprint(loss_records_bp)
    app.register_blueprint(cost_allocations_bp)
    app.register_blueprint(audit_log_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(errors.APIError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(_exc):
        return response.error(errors.ERR_NOT_FOUND, 404, "Path not found.")

    @app.errorhandler(405)
    def handle_405(_exc):
        return response.error(errors.ERR_NOT_FOUND, 404, "Method not allowed for this path.")

    @app.errorhandler(Exception)
    def handle_uncaught(exc):
        # Treat any unanticipated bug as a 500 with a basic envelope.
        body = {
            "meta": {
                "api_request_id": "req_INTERNAL",
                "api_request_timestamp": "",
            },
            "response_type": "error",
            "data": {
                "error_id": "ERR_INTERNAL",
                "message": str(exc),
            },
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
