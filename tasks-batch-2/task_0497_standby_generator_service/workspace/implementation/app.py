"""Standby Generator Service API — Flask entry point.

In-memory store, logical clock, no seeded data. Boots clean on every process.
"""
import os

from flask import Flask

import db
from clock import reset as reset_clock
from errors import ApiError
from response import error as error_response
from routes.onboarding import bp as onboarding_bp
from routes.projects import bp as projects_bp
from routes.units import bp as units_bp
from routes.maintenance import bp as maintenance_bp
from routes.warranty import bp as warranty_bp
from routes.dispatch import bp as dispatch_bp
from routes.recall import bp as recall_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Fresh boot: empty store + default clock. (Module load already gives this,
    # but be explicit so re-imports / test reloads start from a clean slate.)
    db.reset()
    reset_clock()

    app.register_blueprint(onboarding_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(units_bp)
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(warranty_bp)
    app.register_blueprint(dispatch_bp)
    app.register_blueprint(recall_bp)

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
        return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
