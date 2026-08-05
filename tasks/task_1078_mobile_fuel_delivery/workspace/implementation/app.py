"""Mobile Fuel Delivery API — Flask entry point.

In-memory only; no state persists across process restarts and nothing is
seeded at startup. Every entity is created by API calls at test time.
"""
import os

from flask import Flask, jsonify

from core import ApiError, error_response, _meta

from routes.customers import bp as customers_bp
from routes.memberships import bp as memberships_bp
from routes.fleet_accounts import bp as fleet_bp
from routes.vehicles import bp as vehicles_bp
from routes.trucks import bp as trucks_bp
from routes.delivery_routes import bp as routes_bp
from routes.orders import bp as orders_bp
from routes.prices_clock import bp as prices_clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (customers_bp, memberships_bp, fleet_bp, vehicles_bp, trucks_bp,
               routes_bp, orders_bp, prices_clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return jsonify({
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Resource path not found"},
        }), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return jsonify({
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"},
        }), 405

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return jsonify({
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Internal error: %s" % err},
        }), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
