"""Science Center & Planetarium API — Flask entry point.

Boots a fresh, empty in-memory store on every process start. No seeding.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.venues import bp as venues_bp
from routes.memberships import bp as memberships_bp
from routes.shows import bp as shows_bp
from routes.show_bookings import bp as show_bookings_bp
from routes.group_bookings import bp as group_bookings_bp
from routes.programs import bp as programs_bp
from routes.registrations import bp as registrations_bp
from routes.rentals import bp as rentals_bp
from routes.sponsors import bp as sponsors_bp
from routes.accommodations import bp as accommodations_bp
from routes.system import bp as system_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(venues_bp)
    app.register_blueprint(memberships_bp)
    app.register_blueprint(shows_bp)
    app.register_blueprint(show_bookings_bp)
    app.register_blueprint(group_bookings_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(registrations_bp)
    app.register_blueprint(rentals_bp)
    app.register_blueprint(sponsors_bp)
    app.register_blueprint(accommodations_bp)
    app.register_blueprint(system_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
