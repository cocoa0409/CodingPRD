"""Learning-Center Franchise API — Flask entry point.

Boots a fresh, empty in-memory store on every process start. No seeding.
The harness re-launches this process before every test.
"""
import os

from flask import Flask

from errors import ApiError
import errors as errmod
from response import error_response

from routes.clock_route import bp as clock_bp
from routes.centers import bp as centers_bp
from routes.curriculum import bp as curriculum_bp
from routes.families import bp as families_bp
from routes.enrollments import bp as enrollments_bp
from routes.worksheets import bp as worksheets_bp
from routes.sessions import bp as sessions_bp
from routes.attendance import bp as attendance_bp
from routes.invoices import bp as invoices_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(centers_bp)
    app.register_blueprint(curriculum_bp)
    app.register_blueprint(families_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(worksheets_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(invoices_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(_e):
        # Unknown route -> standard ERR_NOT_FOUND envelope.
        return error_response(errmod.not_found("Route not found."))

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response(errmod.not_found("Method not allowed."))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        # Surface unexpected failures inside the standard envelope with a 500 so
        # genuine bugs are visible rather than masquerading as 4xx. Tests should
        # never hit this path.
        return error_response(ApiError("ERR_INTERNAL", 500, f"Unexpected error: {err}"))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
