"""Municipal Aquatics Program & Pool Pass API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding).
"""
import os

from flask import Flask

import envelope
import routes_booking
import routes_facilities
import routes_incidents
import routes_lessons
import routes_patrons
import routes_staff
from errors import ApiError


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return envelope.error_body(err)

    @app.errorhandler(404)
    def handle_404(err):
        return envelope.error_body(
            ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return envelope.error_body(
            ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(500)
    def handle_500(err):
        return envelope.error_body(
            ApiError("ERR_INVALID_REQUEST", 400, "Malformed request"))

    routes_facilities.register(app)
    routes_patrons.register(app)
    routes_lessons.register(app)
    routes_staff.register(app)
    routes_booking.register(app)
    routes_incidents.register(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
