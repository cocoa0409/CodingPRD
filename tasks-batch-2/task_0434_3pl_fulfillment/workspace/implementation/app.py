"""3PL Fulfillment API — entry point, error handlers, route registration.

The in-memory store starts empty on every boot (no seeding). Tests build all
preconditions via the declared API surface.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.clients import bp as clients_bp
from routes.skus import bp as skus_bp
from routes.bins import bp as bins_bp
from routes.inventory_lots import bp as lots_bp
from routes.receipts import bp as receipts_bp
from routes.orders import bp as orders_bp
from routes.waves import bp as waves_bp
from routes.pick_tasks import bp as pick_tasks_bp
from routes.cartons import bp as cartons_bp
from routes.shipments import bp as shipments_bp
from routes.returns import bp as returns_bp
from routes.cycle_counts import bp as cycle_counts_bp
from routes.billing import bp as billing_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clients_bp)
    app.register_blueprint(skus_bp)
    app.register_blueprint(bins_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(receipts_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(waves_bp)
    app.register_blueprint(pick_tasks_bp)
    app.register_blueprint(cartons_bp)
    app.register_blueprint(shipments_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(cycle_counts_bp)
    app.register_blueprint(billing_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body = error_response(e.error_id, e.message)
        resp = jsonify(body)
        resp.status_code = e.http_status
        return resp

    @app.errorhandler(404)
    def handle_404(e):
        body = error_response("ERR_INVALID_REQUEST", "Resource not found")
        resp = jsonify(body)
        resp.status_code = 404
        return resp

    @app.errorhandler(405)
    def handle_405(e):
        body = error_response("ERR_INVALID_REQUEST", "Method not allowed")
        resp = jsonify(body)
        resp.status_code = 405
        return resp

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        body = error_response("ERR_INVALID_REQUEST", "Internal error: %s" % str(e))
        resp = jsonify(body)
        resp.status_code = 400
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
