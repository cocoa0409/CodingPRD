"""Faculty Workload & Course Assignment API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_VALIDATION
from response import error_body

from routes.clock import bp as clock_bp
from routes.terms import bp as terms_bp
from routes.faculty import bp as faculty_bp
from routes.courses import bp as courses_bp
from routes.qualifications import bp as qualifications_bp
from routes.sections import bp as sections_bp
from routes.assignments import bp as assignments_bp
from routes.grants import bp as grants_bp
from routes.overload import bp as overload_bp
from routes.load_sheets import bp as load_sheets_bp


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    for bp in (
        clock_bp,
        terms_bp,
        faculty_bp,
        courses_bp,
        qualifications_bp,
        sections_bp,
        assignments_bp,
        grants_bp,
        overload_bp,
        load_sheets_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_body("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_body("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return error_body(ERR_VALIDATION, "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INTERNAL", f"internal error: {exc}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
