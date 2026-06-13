"""Commissary & Shared Production Kitchen API — Flask entry point.

Registers every blueprint, installs the error/404/405 handlers that emit the
standard envelope, and runs the server in the foreground on 0.0.0.0:$PORT.

The in-memory store starts EMPTY on every boot — nothing is seeded.
"""
import os

from flask import Flask

from errors import ApiError
from response import error
from middleware import get_identity
from routes.members import bp as members_bp
from routes.stations import bp as stations_bp
from routes.bookings import bp as bookings_bp
from routes.storage_units import bp as storage_units_bp
from routes.storage_assignments import bp as storage_assignments_bp
from routes.ingredients import bp as ingredients_bp
from routes.recipes import bp as recipes_bp
from routes.batches import bp as batches_bp
from routes.ingredient_orders import bp as ingredient_orders_bp
from routes.packouts import bp as packouts_bp
from routes.invoices import bp as invoices_bp
from routes.flat import bp as flat_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        members_bp, stations_bp, bookings_bp, storage_units_bp,
        storage_assignments_bp, ingredients_bp, recipes_bp, batches_bp,
        ingredient_orders_bp, packouts_bp, invoices_bp, flat_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        # Unknown route. Require auth first (consistent with the contract), then
        # report not-found. If headers are missing this surfaces 401.
        try:
            get_identity()
        except ApiError as e:
            return error(e.error_id, e.message, e.http_status)
        return error("ERR_NOT_FOUND", "The referenced resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error("ERR_NOT_FOUND", "The referenced resource does not exist.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message, exc.http_status)
        return error("ERR_INVALID_REQUEST", f"Unexpected error: {exc}", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
