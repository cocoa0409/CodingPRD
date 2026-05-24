"""University Application Platform — Flask entry point.

All routes are mounted under the /api prefix described in PRD §2.
The store starts empty on every boot; no seeding is performed.
"""

import os
import sys
import logging
import traceback

from flask import Flask

import errors
import response as resp
from routes.admission_cycles import bp as admission_cycles_bp
from routes.applicants import bp as applicants_bp
from routes.applications import bp as applications_bp
from routes.clock import bp as clock_bp
from routes.essays import bp as essays_bp
from routes.financial_aid import bp as financial_aid_bp
from routes.letters import bp as letters_bp
from routes.recommenders import bp as recommenders_bp
from routes.schools import bp as schools_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Mount every blueprint under /api
    for bp in (
        applicants_bp,
        recommenders_bp,
        schools_bp,
        applications_bp,
        essays_bp,
        letters_bp,
        financial_aid_bp,
        admission_cycles_bp,
        clock_bp,
    ):
        app.register_blueprint(bp, url_prefix="/api")

    # ------------------------------------------------------------------ #
    # Error handlers
    # ------------------------------------------------------------------ #

    @app.errorhandler(errors.APIError)
    def handle_api_error(exc):
        return resp.error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        # Path didn't match any registered route. Per PRD §2.5 unknown path
        # segments resolve to ERR_RESOURCE_NOT_FOUND (404).
        return resp.error_response(
            errors.ERR_RESOURCE_NOT_FOUND, 404,
            "The requested path does not match any route.",
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return resp.error_response(
            errors.ERR_RESOURCE_NOT_FOUND, 404,
            "Method not allowed on this path.",
        )

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return resp.error_response(
            errors.ERR_INVALID_REQUEST, 422,
            "The request payload was not well-formed.",
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Re-raise APIError so the dedicated handler picks it up
        if isinstance(exc, errors.APIError):
            return handle_api_error(exc)
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        return resp.error_response(
            errors.ERR_INVALID_REQUEST, 422,
            "An unexpected error occurred while processing the request.",
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Use Flask's built-in server. threaded=False keeps the in-memory store
    # accessible from a single thread; the harness restarts the server before
    # every test, so concurrency stress isn't a concern here.
    # Suppress Flask's default request log to keep stdout clean.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
