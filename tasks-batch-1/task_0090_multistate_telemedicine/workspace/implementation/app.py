"""Multistate Telemedicine API — Flask entry point.

Boots from a fresh, empty in-memory store on every invocation (no seeding).
Listens on $PORT (default 10000), binds 0.0.0.0, foreground.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.physicians import bp as physicians_bp
from routes.patients import bp as patients_bp
from routes.visits import bp as visits_bp
from routes.followups import bp as followups_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(physicians_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(followups_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route — return the platform's not-found envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        # Surface unexpected failures as a generic invalid-request rather than a
        # bare HTML 500, so the envelope stays consistent.
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % e, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
