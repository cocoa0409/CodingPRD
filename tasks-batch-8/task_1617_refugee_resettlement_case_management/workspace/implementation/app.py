"""Flask application entry point: wiring, locking, and error handlers."""

import os
import threading

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error_response

from routes.cases import bp as cases_bp
from routes.members import bp as members_bp
from routes.housing import bp as housing_bp
from routes.benchmarks import bp as benchmarks_bp
from routes.benefits import bp as benefits_bp
from routes.plans import bp as plans_bp
from routes.sessions import bp as sessions_bp
from routes.notes import bp as notes_bp
from routes.transfers import bp as transfers_bp
from routes.reports import bp as reports_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Serialize requests: the store is plain dicts, and the harness may issue
    # concurrent calls against one server process.
    lock = threading.RLock()

    @app.before_request
    def _acquire_lock():
        lock.acquire()

    @app.teardown_request
    def _release_lock(_exc):
        lock.release()

    for bp in (
        cases_bp,
        members_bp,
        housing_bp,
        benchmarks_bp,
        benefits_bp,
        plans_bp,
        sessions_bp,
        notes_bp,
        transfers_bp,
        reports_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_404(_err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "The requested resource was not found."))

    @app.errorhandler(405)
    def _handle_405(_err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "The requested resource was not found."))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return (
            error_response(ApiError("ERR_INTERNAL", 500, f"Internal server error: {err}")),
            500,
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
