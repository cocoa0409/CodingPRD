"""MTM API entry point: Flask app assembly, error handlers, server boot."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
from util import ApiError, envelope_error
import routes_core
import routes_ops


def create_app():
    app = Flask(__name__)
    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_ops.bp)

    @app.before_request
    def _acquire_lock():
        db.lock.acquire()

    @app.teardown_request
    def _release_lock(exc):
        db.lock.release()

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return envelope_error(e)

    @app.errorhandler(404)
    def handle_404(e):
        return envelope_error(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return envelope_error(ApiError("ERR_NOT_FOUND", 405, "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_exception(e):
        if isinstance(e, HTTPException):
            return envelope_error(
                ApiError("ERR_INVALID_REQUEST", e.code or 400,
                         e.description or "Invalid request"))
        return envelope_error(ApiError("ERR_INVALID_REQUEST", 500, str(e)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
