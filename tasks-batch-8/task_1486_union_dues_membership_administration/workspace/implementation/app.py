"""Union Dues & Membership Administration API — Flask entry point.

Boots an empty in-memory store (no seed data), registers all route
blueprints, and serves on 0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os

from flask import Flask

import db
import errors
from errors import ApiError
from response import error_response

from routes import assessment_runs, clock, elections, employers, locals as locals_bp
from routes import members, objector_cases, per_capita, remittances, sweeps, transfers


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (clock, locals_bp, members, assessment_runs, employers,
                   remittances, objector_cases, transfers, per_capita,
                   elections, sweeps):
        app.register_blueprint(module.bp)

    @app.before_request
    def _acquire_store_lock():
        db.store.lock.acquire()

    @app.teardown_request
    def _release_store_lock(exc=None):
        db.store.lock.release()

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response(errors.err("ERR_INVALID_REQUEST", 404,
                                         "Resource not found"))

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response(errors.err("ERR_INVALID_REQUEST", 405,
                                         "Method not allowed"))

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        app.logger.exception("unexpected error")
        return error_response(errors.err("ERR_INVALID_REQUEST", 400,
                                         "Request could not be processed"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
