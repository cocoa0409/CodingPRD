"""Amusement Park Ride Virtual Queue API — Flask entry point.

Registers all route blueprints, installs the standard error handlers, and binds
0.0.0.0:$PORT. All state is in-memory (see db.py); nothing is seeded at startup.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response
from routes.parks import bp as parks_bp
from routes.rides import bp as rides_bp
from routes.guests import bp as guests_bp
from routes.parties import bp as parties_bp
from routes.plans import bp as plans_bp
from routes.reservations import bp as reservations_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(parks_bp)
    app.register_blueprint(rides_bp)
    app.register_blueprint(guests_bp)
    app.register_blueprint(parties_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(reservations_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> standard NOT_FOUND envelope.
        return response.error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error_response(errors.ERR_VALIDATION, "Method not allowed", 400)

    @app.errorhandler(400)
    def handle_400(exc):
        return response.error_response(errors.ERR_VALIDATION, "Bad request", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exc(exc):
        # Map any other werkzeug HTTP error into the standard envelope.
        status = exc.code or 500
        if status == 404:
            return response.error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)
        return response.error_response(errors.ERR_VALIDATION, exc.description or "Error", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Last-resort guard; never leak a stack trace to the caller.
        return response.error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
