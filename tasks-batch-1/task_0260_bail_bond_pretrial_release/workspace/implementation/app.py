"""Bail Bond & Pretrial Release API — Flask entry point.

In-memory store, no seeding. Boots clean on every invocation.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.bonds import bp as bonds_bp
from routes.court_dates import bp as court_dates_bp
from routes.defendants import bp as defendants_bp
from routes.forfeitures import bp as forfeitures_bp
from routes.gps import bp as gps_bp
from routes.indemnitors import bp as indemnitors_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(defendants_bp)
    app.register_blueprint(bonds_bp)
    app.register_blueprint(indemnitors_bp)
    app.register_blueprint(court_dates_bp)
    app.register_blueprint(gps_bp)
    app.register_blueprint(forfeitures_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route / method-not-found path -> generic not found envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Surface unexpected errors as a 400 invalid-request envelope rather than
        # an HTML 500, keeping the response contract intact.
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
