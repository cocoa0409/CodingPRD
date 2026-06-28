"""Spin Studio API — Flask entry point.

In-memory storage only; store starts empty on every boot (no seeding).
Boots from a fresh process on every invocation (per-test-server isolation).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.facilities import bp as facilities_bp
from routes.sessions import bp as sessions_bp
from routes.members import bp as members_bp
from routes.reservations import bp as reservations_bp
from routes.waitlist import bp as waitlist_bp
from routes.retail import bp as retail_bp
from routes.penalties import bp as penalties_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(facilities_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(waitlist_bp)
    app.register_blueprint(retail_bp)
    app.register_blueprint(penalties_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route — surface as ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_VALIDATION", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, HTTPException):
            return error_response("ERR_VALIDATION", str(e), e.code or 400)
        return error_response("ERR_VALIDATION", "Internal error: %s" % e, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
