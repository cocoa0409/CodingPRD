"""Flask application entry point: registration + global error handling."""
import os

from flask import Flask, jsonify

from errors import ApiError
from web import error_response, _meta
from routes.catalog import bp as catalog_bp
from routes.departures import bp as departures_bp
from routes.hotel_blocks import bp as hotel_blocks_bp
from routes.bookings import bp as bookings_bp
from routes.passengers import bp as passengers_bp
from routes.payments import bp as payments_bp
from routes.vouchers import bp as vouchers_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(departures_bp)
    app.register_blueprint(hotel_blocks_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(passengers_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(vouchers_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(_err):
        return error_response(ApiError("ERR_NOT_FOUND", "Resource not found"))

    @app.errorhandler(405)
    def handle_405(_err):
        return error_response(ApiError("ERR_NOT_FOUND", "Method not allowed"))

    @app.errorhandler(400)
    def handle_400(_err):
        return error_response(ApiError("ERR_VALIDATION", "Bad request"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
