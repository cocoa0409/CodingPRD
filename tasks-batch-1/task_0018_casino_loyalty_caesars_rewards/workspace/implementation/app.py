"""Caesars Rewards Loyalty API — Flask entry point.

Boots empty on every process start (per Step 6 contract: no seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.clock_route import bp as clock_bp
from routes.members import bp as members_bp
from routes.properties import bp as properties_bp
from routes.hosts import bp as hosts_bp
from routes.host_assignments import bp as host_assignments_bp
from routes.gaming_sessions import bp as gaming_sessions_bp
from routes.comp_room_bookings import bp as comp_room_bookings_bp
from routes.self_exclusions import bp as self_exclusions_bp
from routes.velocity_alerts import bp as velocity_alerts_bp
from routes.annual_reset_runs import bp as annual_reset_runs_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        members_bp,
        properties_bp,
        hosts_bp,
        host_assignments_bp,
        gaming_sessions_bp,
        comp_room_bookings_bp,
        self_exclusions_bp,
        velocity_alerts_bp,
        annual_reset_runs_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(e: ApiError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _404(_e):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def _405(_e):
        return error_response(ERR_INVALID_REQUEST, "method not allowed", 405)

    @app.errorhandler(HTTPException)
    def _http(e: HTTPException):
        return error_response(ERR_INVALID_REQUEST, e.description or "bad request",
                              e.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(e):
        return error_response(ERR_INVALID_REQUEST, f"internal: {type(e).__name__}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
