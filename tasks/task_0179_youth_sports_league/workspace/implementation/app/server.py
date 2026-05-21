"""Flask app factory: wires routes, error handler, auth hook."""
from __future__ import annotations

from flask import Flask, request

from .auth import authenticate
from .errors import APIError
from .response import error_response
from .routes.audit_routes import audit_bp
from .routes.clock_routes import clock_bp
from .routes.coach_routes import coach_bp
from .routes.game_routes import game_bp
from .routes.guardian_routes import guardian_bp
from .routes.health_routes import health_bp
from .routes.player_routes import player_bp
from .routes.referee_routes import referee_bp
from .routes.season_routes import season_bp
from .routes.shift_routes import shift_bp
from .routes.team_routes import team_bp


# Endpoints that are exempt from the X-User-ID / X-User-Role header requirement.
AUTH_EXEMPT_PATHS = {"/_clock/advance", "/healthz"}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    app.register_blueprint(season_bp)
    app.register_blueprint(player_bp)
    app.register_blueprint(team_bp)
    app.register_blueprint(coach_bp)
    app.register_blueprint(referee_bp)
    app.register_blueprint(guardian_bp)
    app.register_blueprint(game_bp)
    app.register_blueprint(shift_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(clock_bp)
    app.register_blueprint(health_bp)

    # ------------------------------------------------------------------
    # Auth hook: runs before every request. Auth-exempt endpoints skip it.
    # ------------------------------------------------------------------
    @app.before_request
    def _auth_hook():
        path = request.path
        if path in AUTH_EXEMPT_PATHS:
            return None
        try:
            authenticate()
        except APIError as e:
            return error_response(e.error_id, e.message, e.http_status)
        return None

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------
    @app.errorhandler(APIError)
    def _handle_api_error(err: APIError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _handle_404(_):
        return error_response("ERR_VALIDATION", "Route not found.", 404)

    @app.errorhandler(405)
    def _handle_405(_):
        return error_response("ERR_VALIDATION", "Method not allowed.", 405)

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception):
        # Last-resort safety net; surface as 500.
        return error_response("ERR_VALIDATION", f"Internal error: {err}", 500)

    return app
