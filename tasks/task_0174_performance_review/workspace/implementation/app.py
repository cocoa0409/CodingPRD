"""Application entrypoint.

Listens on PORT (default 10000), bound to 0.0.0.0, single Flask process.
Per INSTRUCTION.md.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import AppError
from middleware import before_request_hook
from response import err as err_response


def create_app() -> Flask:
    app = Flask(__name__)

    # Register before_request middleware (auth + request id mint).
    app.before_request(before_request_hook)

    # Register route blueprints.
    from routes.employees import bp as employees_bp
    from routes.cycles import bp as cycles_bp
    from routes.review_cases import bp as review_cases_bp
    from routes.goals import bp as goals_bp
    from routes.feedback_requests import bp as feedback_requests_bp
    from routes.calibration_sessions import bp as calibration_sessions_bp
    from routes.pip_cases import bp as pip_cases_bp
    from routes.comp_plans import bp as comp_plans_bp
    from routes.audit_events import bp as audit_events_bp
    from routes.clock_admin import bp as clock_admin_bp

    app.register_blueprint(employees_bp)
    app.register_blueprint(cycles_bp)
    app.register_blueprint(review_cases_bp)
    app.register_blueprint(goals_bp)
    app.register_blueprint(feedback_requests_bp)
    app.register_blueprint(calibration_sessions_bp)
    app.register_blueprint(pip_cases_bp)
    app.register_blueprint(comp_plans_bp)
    app.register_blueprint(audit_events_bp)
    app.register_blueprint(clock_admin_bp)

    @app.errorhandler(AppError)
    def handle_app_error(e: AppError):
        return err_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Routes that don't match any blueprint — generic not found.
        return err_response(
            "ERR_NOT_FOUND",
            "Resource not found.",
            404,
        )

    @app.errorhandler(405)
    def handle_405(e):
        return err_response(
            "ERR_VALIDATION",
            "Method not allowed for this endpoint.",
            405,
        )

    @app.errorhandler(HTTPException)
    def handle_http(e: HTTPException):
        code = e.code or 500
        if code == 400:
            return err_response("ERR_VALIDATION", e.description or "Bad request.", 400)
        if code == 404:
            return err_response("ERR_NOT_FOUND", "Resource not found.", 404)
        return err_response("ERR_VALIDATION", e.description or "HTTP error.", code)

    @app.errorhandler(Exception)
    def handle_uncaught(e: Exception):
        # Last-resort guard. Never raise the body of the exception.
        return err_response(
            "ERR_VALIDATION",
            "Internal server error.",
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    # Threaded so concurrent tests share the same in-memory store via the
    # global store.lock for serialisation.
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
