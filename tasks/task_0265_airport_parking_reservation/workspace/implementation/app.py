"""Airport Parking Reservation API — Flask entry point.

In-memory state only. The store starts empty on every boot (no seeding).
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.clock import bp as clock_bp
from routes.customers import bp as customers_bp
from routes.lots import bp as lots_bp
from routes.reservations import bp as reservations_bp
from routes.shuttle_trips import bp as shuttle_trips_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(shuttle_trips_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body = error_response(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def handle_404(_exc):
        body = error_response("ERR_NOT_FOUND", "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(400)
    def handle_400(_exc):
        body = error_response("ERR_VALIDATION", "Malformed request.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_uncaught(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        # Let werkzeug routing/HTTP exceptions (404, 405, ...) be handled by
        # their own handlers / defaults rather than masking them as 400.
        if isinstance(exc, HTTPException):
            return exc
        body = error_response("ERR_VALIDATION", "Unexpected server error: %s" % exc)
        return jsonify(body), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
