"""ASC Scheduling API — entry point, error handlers, route registration.

Storage is in-memory only (db.py); the store starts EMPTY on every boot.
No seeding, no preloaded entities.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response
from routes.resources import bp as resources_bp
from routes.days import bp as days_bp
from routes.blocks import bp as blocks_bp
from routes.cases import bp as cases_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(resources_bp)
    app.register_blueprint(days_bp)
    app.register_blueprint(blocks_bp)
    app.register_blueprint(cases_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route — return the envelope shape with a generic not-found.
        return error_response("ERR_INVALID_REQUEST", 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed.")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.http_status, exc.message)
        return error_response("ERR_INVALID_REQUEST", 400, "Bad request: %s" % str(exc))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
