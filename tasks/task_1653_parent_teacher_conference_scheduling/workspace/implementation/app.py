"""Flask entry point: app factory, error handlers, blueprint registration."""

import os

from flask import Flask

import errors
import response
from routes import attendance, bookings, clock, families, interpreter_requests, \
    interpreters, outreach, slots, teachers, waitlist, windows


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock.bp)
    app.register_blueprint(windows.bp)
    app.register_blueprint(teachers.bp)
    app.register_blueprint(families.bp)
    app.register_blueprint(slots.bp)
    app.register_blueprint(bookings.bp)
    app.register_blueprint(interpreters.bp)
    app.register_blueprint(interpreter_requests.bp)
    app.register_blueprint(waitlist.bp)
    app.register_blueprint(attendance.bp)
    app.register_blueprint(outreach.bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return response.error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return response.error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return response.error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return response.error_response("ERR_VALIDATION", 500, str(err))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
