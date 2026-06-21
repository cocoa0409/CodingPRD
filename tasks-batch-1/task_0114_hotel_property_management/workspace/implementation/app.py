"""Hotel Property Management System (PMS) — Flask entry point.

In-memory only. No entity is seeded at startup; the store starts empty and is
wiped on every fresh boot (module-level dicts in db.py). All entity data is
created by tests via the declared API surface.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_response
from routes.audit import bp as audit_bp
from routes.config import bp as config_bp
from routes.folios import bp as folios_bp
from routes.group_blocks import bp as group_blocks_bp
from routes.reservations import bp as reservations_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(group_blocks_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(folios_bp)
    app.register_blueprint(audit_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        if e.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        if e.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)
        return error_response("ERR_INVALID_REQUEST", str(e), e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Last-resort guard; surface as a generic invalid request rather than 500.
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
