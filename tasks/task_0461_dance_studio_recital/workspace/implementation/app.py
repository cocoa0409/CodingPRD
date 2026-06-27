"""Dance Studio & Recital Management API — entry point."""
import os

from flask import Flask

from errors import ApiError
from response import error_response, success
from routes.clock import bp as clock_bp
from routes.families import bp as families_bp
from routes.students import bp as students_bp
from routes.config import bp as config_bp
from routes.sections import bp as sections_bp
from routes.enrollments import bp as enrollments_bp
from routes.attendance import bp as attendance_bp
from routes.costumes import bp as costumes_bp
from routes.recitals import bp as recitals_bp
from routes.teams import bp as teams_bp
from routes.trips import bp as trips_bp
from routes.invoices import bp as invoices_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp, families_bp, students_bp, config_bp, sections_bp,
        enrollments_bp, attendance_bp, costumes_bp, recitals_bp,
        teams_bp, trips_bp, invoices_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body = error_response(e.error_id, e.message)
        return body, e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        body = error_response("ERR_NOT_FOUND", "Resource not found.")
        return body, 404

    @app.errorhandler(405)
    def handle_405(e):
        body = error_response("ERR_FORBIDDEN_ROLE", "Method not allowed.")
        return body, 405

    @app.errorhandler(400)
    def handle_400(e):
        body = error_response("ERR_INVALID_REQUEST", "Malformed request.")
        return body, 400

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        body = error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e)
        return body, 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
