"""Entry point: Flask app, error handlers, blueprint registration.

The in-memory store starts EMPTY on every boot. No entity is seeded, preloaded,
or hardcoded at startup — every entity is created by the test suite via the
declared API surface.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.catalog import bp as catalog_bp
from routes.families import bp as families_bp
from routes.sessions import bp as sessions_bp
from routes.enrollments import bp as enrollments_bp
from routes.invoices import bp as invoices_bp
from routes.makeups import bp as makeups_bp
from routes.assessments import bp as assessments_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(families_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(makeups_bp)
    app.register_blueprint(assessments_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route — no entity-specific not-found applies.
        return error_response("ERR_INVALID_REQUEST", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
