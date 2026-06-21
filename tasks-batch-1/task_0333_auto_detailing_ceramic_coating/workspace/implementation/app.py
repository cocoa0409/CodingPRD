"""Auto Detailing & Ceramic Coating API — entry point.

In-memory only. State lives in db.py module-level dicts and is wiped on every
process boot (nothing is seeded). The test harness restarts this process via
start.sh before each test.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.catalog import bp as catalog_bp
from routes.memberships import bp as memberships_bp
from routes.appointments import bp as appointments_bp
from routes.transitions import bp as transitions_bp
from routes.rework import bp as rework_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(memberships_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(transitions_bp)
    app.register_blueprint(rework_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, HTTPException):
            return error_response("ERR_VALIDATION", e.code or 400, str(e))
        return error_response("ERR_VALIDATION", 500, "internal error")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
