"""Entry point: app factory, error handlers, route registration, server run.

In-memory state only. The store starts empty on every boot; nothing is seeded.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import db
from errors import ApiError
from response import error_response
from routes.backups import bp as backups_bp
from routes.bookings import bp as bookings_bp
from routes.catalogue import bp as catalogue_bp
from routes.contracts import bp as contracts_bp
from routes.payments import bp as payments_bp
from routes.songs import bp as songs_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Serialize every request behind the store lock. The model is "immediate
    # consistency" and all state lives in process memory; a global lock keeps
    # multi-threaded request handling race-free without per-entity locking.
    @app.before_request
    def _acquire_lock():
        db.LOCK.acquire()
        g._locked = True

    @app.teardown_request
    def _release_lock(exc=None):
        if g.pop("_locked", False):
            try:
                db.LOCK.release()
            except RuntimeError:
                pass

    app.register_blueprint(catalogue_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(songs_bp)
    app.register_blueprint(backups_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND",
                              "Method not allowed for this path", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        if isinstance(err, HTTPException):
            code = err.code or 500
            if code == 404:
                return error_response("ERR_NOT_FOUND", "Resource not found", 404)
            if code == 405:
                return error_response("ERR_NOT_FOUND",
                                      "Method not allowed for this path", 404)
            if code == 400:
                return error_response("ERR_INVALID_REQUEST",
                                      "Malformed request", 422)
            return error_response("ERR_INVALID_REQUEST", err.description, code)
        return error_response("ERR_INVALID_REQUEST", str(err), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
