"""Merchant Mariner Crewing API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding).
Listens on 0.0.0.0:$PORT (default 10000) in the foreground.
"""

import os

from flask import Flask

from db import store
from errors import ApiError, err
from response import error_response
from routes_assignments import bp as assignments_bp
from routes_clock import bp as clock_bp
from routes_credentials import bp as credentials_bp
from routes_mariners import bp as mariners_bp
from routes_medical import bp as medical_bp
from routes_sea_service import bp as sea_service_bp
from routes_training import bp as training_bp
from routes_union import bp as union_bp
from routes_vessels import bp as vessels_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        mariners_bp,
        credentials_bp,
        sea_service_bp,
        medical_bp,
        vessels_bp,
        assignments_bp,
        training_bp,
        union_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    # Serialize requests through one lock so cascades stay atomic.
    @app.before_request
    def _acquire():
        store.lock.acquire()

    @app.teardown_request
    def _release(exc):
        store.lock.release()

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err("ERR_INVALID_REQUEST", "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err("ERR_INVALID_REQUEST", "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return error_response(
            err("ERR_INVALID_REQUEST", "Malformed request: %s" % e)
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
