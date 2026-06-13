"""Volunteer Management API — Flask entry point.

Registers every resource blueprint and the global error/404/405 handlers.
Storage is in-memory only (see db.py); the store starts EMPTY on every boot —
no entity is seeded, preloaded, or hardcoded at startup. start.sh re-invocation
therefore wipes all state and guarantees a fresh boot.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.organizations import bp as organizations_bp
from routes.volunteers import bp as volunteers_bp
from routes.background_checks import bp as background_checks_bp
from routes.catalog import bp as catalog_bp
from routes.opportunities import bp as opportunities_bp
from routes.signups import bp as signups_bp
from routes.corporate_groups import bp as corporate_groups_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(organizations_bp)
    app.register_blueprint(volunteers_bp)
    app.register_blueprint(background_checks_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(opportunities_bp)
    app.register_blueprint(signups_bp)
    app.register_blueprint(corporate_groups_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route — return the envelope shape with a generic not-found.
        return error_response("ERR_INVALID_REQUEST", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
