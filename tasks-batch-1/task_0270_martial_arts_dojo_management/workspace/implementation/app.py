"""Martial Arts Dojo Management API — Flask entry point.

In-memory storage only; the store starts EMPTY on every process boot. No
seeding, no preloaded entities — every entity is created by tests through the
declared API surface.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_response

from routes.programs import bp as programs_bp
from routes.families import bp as families_bp
from routes.members import bp as members_bp
from routes.instructors import bp as instructors_bp
from routes.enrollments import bp as enrollments_bp
from routes.class_sessions import bp as class_sessions_bp
from routes.attendances import bp as attendances_bp
from routes.promotion_tests import bp as promotion_tests_bp
from routes.contracts import bp as contracts_bp
from routes.invoices import bp as invoices_bp
from routes.private_lessons import bp as private_lessons_bp
from routes.tournament_registrations import bp as tournament_registrations_bp
from routes.pro_shop_orders import bp as pro_shop_orders_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        programs_bp, families_bp, members_bp, instructors_bp, enrollments_bp,
        class_sessions_bp, attendances_bp, promotion_tests_bp, contracts_bp,
        invoices_bp, private_lessons_bp, tournament_registrations_bp,
        pro_shop_orders_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, HTTPException):
            return exc
        return error_response("ERR_INVALID_REQUEST", "Unexpected error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
