"""Pottery & Ceramics Studio API — entry point.

Boots a fresh, EMPTY in-memory store on every process start. No seeding, no
preloading, no persistence. start.sh re-invocation wipes all state because the
store (db.py) is reconstructed at import time.

Reads $PORT (default 10000), binds 0.0.0.0, runs in the foreground.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error as error_response

# Route blueprints
from routes.loyalty_members import bp as loyalty_members_bp
from routes.paint_bar_items import bp as paint_bar_items_bp
from routes.studio_visits import bp as studio_visits_bp
from routes.bisque_pieces import bp as bisque_pieces_bp
from routes.kiln_batches import bp as kiln_batches_bp
from routes.party_bookings import bp as party_bookings_bp
from routes.class_series import bp as class_series_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(loyalty_members_bp)
    app.register_blueprint(paint_bar_items_bp)
    app.register_blueprint(studio_visits_bp)
    app.register_blueprint(bisque_pieces_bp)
    app.register_blueprint(kiln_batches_bp)
    app.register_blueprint(party_bookings_bp)
    app.register_blueprint(class_series_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Invalid request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface any unhandled exception as a structured 400 invalid-request so
        # the harness never sees a bare HTML 500.
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", "Invalid request: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
