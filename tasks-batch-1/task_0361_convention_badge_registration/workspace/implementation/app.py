"""Convention & Badge Registration API — Flask entry point.

In-memory storage only; the store starts empty on every fresh boot. No seeding.
Listens on $PORT (default 10000), binds 0.0.0.0, runs in the foreground.
"""
import os

from flask import Flask

import errors
import response
from routes import (
    attendees,
    badges,
    booths,
    clock_route,
    conventions,
    exhibitors,
    orders,
    sessions,
    waitlist,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(conventions.bp)
    app.register_blueprint(attendees.bp)
    app.register_blueprint(exhibitors.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(badges.bp)
    app.register_blueprint(sessions.bp)
    app.register_blueprint(waitlist.bp)
    app.register_blueprint(booths.bp)
    app.register_blueprint(clock_route.bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        # Unknown route -> resource not found in the standard envelope.
        return response.error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return response.error("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Defensive: surface unexpected failures as a malformed-request error rather
        # than leaking an HTML stack trace that would break envelope-parsing tests.
        if isinstance(exc, errors.ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        return response.error("ERR_INVALID_REQUEST", "Unexpected error: %s" % exc, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
