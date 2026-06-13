"""Auto Title Loan API — Flask entry point.

In-memory storage only; the store starts empty on every boot. No entities are
seeded at startup. Binds 0.0.0.0:$PORT (default 10000), foreground.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes_core import bp as core_bp
from routes_applications import bp as applications_bp
from routes_loans import bp as loans_bp
from routes_liens import bp as liens_bp
from routes_repossession import bp as repossession_bp
from routes_devices import bp as devices_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(core_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(liens_bp)
    app.register_blueprint(repossession_bp)
    app.register_blueprint(devices_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> ERR_NOT_FOUND envelope (PRD 2.5).
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Surface unexpected failures as a generic invalid-request envelope so
        # the harness still receives the standard error structure.
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", "unexpected error: %s" % e, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
