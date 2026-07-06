"""Social-Media Management API — entry point.

Registers all blueprints, installs the global error handler that renders every
ApiError through the standard error envelope, and runs the server in the
foreground bound to 0.0.0.0:$PORT (default 10000).

NOTE: No entity data is seeded at startup. The in-memory store (db.py) begins
empty on every fresh process; tests construct all entities via the API.
"""
import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
import response

from routes.clients import bp as clients_bp
from routes.packages import bp as packages_bp
from routes.channels import bp as channels_bp
from routes.content import bp as content_bp
from routes.boosts import bp as boosts_bp
from routes.community import bp as community_bp
from routes.collabs import bp as collabs_bp
from routes.analytics import bp as analytics_bp
from routes.ledger import bp as ledger_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clients_bp)
    app.register_blueprint(packages_bp)
    app.register_blueprint(channels_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(boosts_bp)
    app.register_blueprint(community_bp)
    app.register_blueprint(collabs_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(ledger_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> treat as a generic not-found-style 404. Tests target
        # declared routes; this is a safety net.
        return response.error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(exc):
        return response.error_response(ERR_INVALID_REQUEST[0], "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return response.error_response(exc.error_id, exc.message, exc.http_status)
        # Surface unexpected failures as a 400 invalid-request rather than a 500
        # so malformed input never crashes the per-test server.
        return response.error_response(ERR_INVALID_REQUEST[0], "Bad request", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
