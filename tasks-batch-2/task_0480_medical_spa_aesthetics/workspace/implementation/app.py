"""Medical Spa & Aesthetics API — entry point, error handlers, route registration.

In-memory storage only; store starts empty on every boot (no seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.catalog import bp as catalog_bp
from routes.clinical import bp as clinical_bp
from routes.plans import bp as plans_bp
from routes.sessions import bp as sessions_bp
from routes.complications import bp as complications_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(clinical_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(complications_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route -> generic invalid request (kept distinct from
        # resource-specific not-found errors, which are raised explicitly).
        return error_response("ERR_INVALID_REQUEST", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, HTTPException):
            return error_response("ERR_INVALID_REQUEST", err.description or "HTTP error",
                                  err.code or 400)
        return error_response("ERR_INVALID_REQUEST", "Internal error", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
