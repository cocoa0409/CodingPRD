"""Entry point: Flask app, error handlers, blueprint registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.years import bp as years_bp
    from routes.families import bp as families_bp
    from routes.students import bp as students_bp
    from routes.enrollments import bp as enrollments_bp
    from routes.notices import bp as notices_bp
    from routes.plans import bp as plans_bp
    from routes.attendance import bp as attendance_bp
    from routes.portfolios import bp as portfolios_bp
    from routes.exams import bp as exams_bp
    from routes.credits import bp as credits_bp
    from routes.coop import bp as coop_bp
    from routes.graduation import bp as graduation_bp
    from routes.reports import bp as reports_bp
    from routes.clock_route import bp as clock_bp

    for bp in (
        years_bp, families_bp, students_bp, enrollments_bp, notices_bp,
        plans_bp, attendance_bp, portfolios_bp, exams_bp, credits_bp,
        coop_bp, graduation_bp, reports_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_generic(err):
        import traceback
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", 400, str(err))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
