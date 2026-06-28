"""Hotel Revenue Management System — Flask entry point.

Boots a fresh in-memory store on every process start (no seeding). Registers
all route blueprints and the global error handlers that wrap every response in
the standard envelope (PRD §2.2).
"""
import os

from flask import Flask, jsonify

from errors import ApiError, HTTP_STATUS, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.clock import bp as clock_bp
from routes.properties import bp as properties_bp
from routes.room_types import bp as room_types_bp
from routes.rate_plans import bp as rate_plans_bp
from routes.inventory_days import bp as inventory_days_bp
from routes.yield_rules import bp as yield_rules_bp
from routes.rate_decisions import bp as rate_decisions_bp
from routes.channel_mappings import bp as channel_mappings_bp
from routes.group_blocks import bp as group_blocks_bp
from routes.competitor_rates import bp as competitor_rates_bp
from routes.transient_reservations import bp as transient_reservations_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(room_types_bp)
    app.register_blueprint(rate_plans_bp)
    app.register_blueprint(inventory_days_bp)
    app.register_blueprint(yield_rules_bp)
    app.register_blueprint(rate_decisions_bp)
    app.register_blueprint(channel_mappings_bp)
    app.register_blueprint(group_blocks_bp)
    app.register_blueprint(competitor_rates_bp)
    app.register_blueprint(transient_reservations_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body = error_response(e.error_id, e.message)
        return jsonify(body), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> ERR_NOT_FOUND envelope.
        body = error_response(ERR_NOT_FOUND, "Resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(e):
        body = error_response(ERR_NOT_FOUND, "Method not allowed")
        return jsonify(body), 404

    @app.errorhandler(400)
    def handle_400(e):
        body = error_response(ERR_INVALID_REQUEST, "Malformed request")
        return jsonify(body), HTTP_STATUS[ERR_INVALID_REQUEST]

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Re-raise ApiError so its own handler runs.
        if isinstance(e, ApiError):
            return handle_api_error(e)
        body = error_response("ERR_INTERNAL", "Internal server error")
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
