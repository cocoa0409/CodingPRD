"""Full-Time Virtual K-12 School API -- Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_body

from routes.clock import bp as clock_bp
from routes.districts import bp as districts_bp
from routes.students import bp as students_bp
from routes.stipends import bp as stipends_bp
from routes.teachers import bp as teachers_bp
from routes.attendance import bp as attendance_bp
from routes.assessments import bp as assessments_bp
from routes.service_deliveries import bp as service_deliveries_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        clock_bp,
        districts_bp,
        students_bp,
        stipends_bp,
        teachers_bp,
        attendance_bp,
        assessments_bp,
        service_deliveries_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_body(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_body(ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return error_body(ERR_INVALID_REQUEST, "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INTERNAL", f"internal error: {exc}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
