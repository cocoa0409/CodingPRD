"""Tow & Impound Lot Management API — Flask entry point.

In-memory storage only (see db.py): every collection is a dict keyed by id and
is empty on every process boot. NO entity data is seeded, preloaded, or
hardcoded at startup. start.sh re-invocation wipes all state.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.auctions import bp as auctions_bp
from routes.clock_routes import bp as clock_bp
from routes.fee_waivers import bp as fee_waivers_bp
from routes.inventory_items import bp as inventory_bp
from routes.lienholders import bp as lienholders_bp
from routes.lots import bp as lots_bp
from routes.notifications import bp as notifications_bp
from routes.providers import bp as providers_bp
from routes.release_records import bp as release_bp
from routes.rotation_assignments import bp as rotation_bp
from routes.tow_orders import bp as tow_orders_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(lots_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(lienholders_bp)
    app.register_blueprint(rotation_bp)
    app.register_blueprint(tow_orders_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(fee_waivers_bp)
    app.register_blueprint(release_bp)
    app.register_blueprint(auctions_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % err, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
