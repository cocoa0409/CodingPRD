"""Chiropractic Practice API — Flask entry point.

In-memory storage only; no entity data is seeded at startup. State is wiped on
every process restart (per-test-server isolation).
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.config import bp as config_bp
from routes.patients import bp as patients_bp
from routes.clinical import bp as clinical_bp
from routes.appointments import bp as appointments_bp
from routes.search import bp as search_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(clinical_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(search_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_RESOURCE_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_RESOURCE_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", 400, "Bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 400, "Unexpected error: %s" % str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
