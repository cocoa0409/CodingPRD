"""Powersports Dealer & Service API — Flask entry point.

In-memory storage only; fresh empty state on every boot. No seeding.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body

from routes.misc import bp as misc_bp
from routes.units import bp as units_bp
from routes.curtailments import bp as curtailments_bp
from routes.trade_ins import bp as trade_ins_bp
from routes.deals import bp as deals_bp
from routes.technicians import bp as technicians_bp
from routes.repair_orders import bp as repair_orders_bp
from routes.service_lines import bp as service_lines_bp
from routes.parts import bp as parts_bp
from routes.storage import bp as storage_bp
from routes.waivers import bp as waivers_bp
from routes.warranty import bp as warranty_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(misc_bp)
    app.register_blueprint(units_bp)
    app.register_blueprint(curtailments_bp)
    app.register_blueprint(trade_ins_bp)
    app.register_blueprint(deals_bp)
    app.register_blueprint(technicians_bp)
    app.register_blueprint(repair_orders_bp)
    app.register_blueprint(service_lines_bp)
    app.register_blueprint(parts_bp)
    app.register_blueprint(storage_bp)
    app.register_blueprint(waivers_bp)
    app.register_blueprint(warranty_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body = error_body(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route — return the standard error envelope.
        body = error_body("ERR_NOT_FOUND", "Resource or route not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(exc):
        body = error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed")
        return jsonify(body), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        body = error_body("ERR_INTERNAL", str(exc))
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
