"""Ghost Kitchen & Virtual Brand Platform API — Flask entry point.

In-memory only. Storage is wiped on every process boot (no persistence, no
seeding). Every entity is constructed by clients via the declared API surface.
"""
import os

from flask import Flask, jsonify

import errors
from response import error_response
from routes.stalls import bp as stalls_bp
from routes.brands import bp as brands_bp
from routes.leases import bp as leases_bp
from routes.equipment import bp as equipment_bp
from routes.bookings import bp as bookings_bp
from routes.menu_items import bp as menu_items_bp
from routes.ingredient_lots import bp as ingredient_lots_bp
from routes.orders import bp as orders_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(stalls_bp)
    app.register_blueprint(brands_bp)
    app.register_blueprint(leases_bp)
    app.register_blueprint(equipment_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(menu_items_bp)
    app.register_blueprint(ingredient_lots_bp)
    app.register_blueprint(orders_bp)

    # ---- Error handlers -> standard error envelope ----
    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / path id not resolving at the routing layer.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface unexpected failures as a 500 in the standard envelope so the
        # response shape stays consistent.
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
