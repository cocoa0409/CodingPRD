"""Houseboat Charter Rental API — entry point.

Binds 0.0.0.0:$PORT (default 10000). All state is in-memory; the store starts
empty on every boot and the logical clock reads exactly 2026-08-01T00:00:00Z
until a FleetManager advances it via POST /_clock/set_current_utc.
"""

import os

from flask import Flask

import errors
import response
from routes import bookings, charter, fleet, ops, renters


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    app.register_blueprint(fleet.bp)
    app.register_blueprint(renters.bp)
    app.register_blueprint(bookings.bp)
    app.register_blueprint(charter.bp)
    app.register_blueprint(ops.bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_):
        return response.error(
            errors.ERR_NOT_FOUND, "Resource not found", 404
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(_):
        return response.error(
            errors.ERR_INVALID_REQUEST, "Method not allowed", 405
        )

    @app.errorhandler(500)
    def handle_internal(exc):
        return response.error(
            errors.ERR_INVALID_REQUEST, f"Internal error: {exc}", 500
        )

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
