"""Entry point: Flask app, error handlers, blueprint registration.

Storage is in-memory only and starts EMPTY on every boot — no seeding.
"""
import os

from flask import Flask, request

import db
from errors import ApiError
from response import error_response
from routes.catalog import bp as catalog_bp
from routes.contracts import bp as contracts_bp
from routes.equipment import bp as equipment_bp
from routes.reservations import bp as reservations_bp
from routes.transfers import bp as transfers_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(equipment_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(transfers_bp)

    # Serialize all write requests under a single lock for consistency
    # (the OCC tests model concurrent writers via stale versions, not threads).
    @app.before_request
    def _acquire_lock():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            db.LOCK.acquire()

    @app.teardown_request
    def _release_lock(exc):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            try:
                db.LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 422, "Unexpected error: %s" % str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
