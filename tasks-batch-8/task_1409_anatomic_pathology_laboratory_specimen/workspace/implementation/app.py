"""Anatomic Pathology Lab API — Flask entry point.

The in-memory store starts empty on every boot; the logical clock starts at
exactly 2026-08-01T00:00:00Z and never falls back to wall time.
"""
import os

from flask import Flask

from db import db
from errors import ApiError
from helpers import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    import routes_admin
    import routes_cases
    import routes_lab
    import routes_review
    app.register_blueprint(routes_admin.bp)
    app.register_blueprint(routes_cases.bp)
    app.register_blueprint(routes_lab.bp)
    app.register_blueprint(routes_review.bp)

    # Serialize requests against the in-memory store so concurrent OCC writes
    # cannot interleave between check and mutation.
    @app.before_request
    def _acquire_store():
        db.lock.acquire()

    @app.teardown_request
    def _release_store(exc):
        db.lock.release()

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404,
                                       "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404,
                                       "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError("ERR_INVALID_REQUEST", 400,
                                       "Malformed request"))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
