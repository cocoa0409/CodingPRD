"""Patent Application Filing API — Flask entrypoint.

Wires up the blueprints, installs the standard error envelope on every
ApiError, and starts a Flask server bound to 0.0.0.0 on the PORT env var
(default 10000) per INSTRUCTION.md.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, make_error
from response import error as error_response
from routes.applicants import applicants_bp
from routes.applications import applications_bp
from routes.clock import clock_bp
from routes.maintenance_fees import maintenance_fees_bp
from routes.office_actions import office_actions_bp
from routes.pct_phases import pct_phases_bp
from routes.test_infra import test_infra_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(applicants_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(office_actions_bp)
    app.register_blueprint(maintenance_fees_bp)
    app.register_blueprint(pct_phases_bp)
    app.register_blueprint(clock_bp)
    app.register_blueprint(test_infra_bp)

    # -----------------------------------------------------------------
    # Error handlers
    # -----------------------------------------------------------------
    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        err = make_error("ERR_NOT_FOUND", "Route not found.")
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(405)
    def handle_405(exc):
        err = make_error("ERR_BAD_REQUEST", "Method not allowed.")
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(400)
    def handle_400(exc):
        err = make_error("ERR_BAD_REQUEST", "Malformed request.")
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException):
        code = exc.code or 500
        if code == 404:
            return handle_404(exc)
        if code == 405:
            return handle_405(exc)
        err = make_error("ERR_BAD_REQUEST", exc.description or "HTTP exception")
        return error_response(err.error_id, err.message, code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        return error_response("ERR_BAD_REQUEST", f"Internal error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
