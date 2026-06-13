"""Weight Management & Nutrition Program API — entry point.

In-memory only. No seeding. Boots clean on every process start.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error as error_response

from routes.programs import bp as programs_bp
from routes.plans import bp as plans_bp
from routes.members import bp as members_bp
from routes.coaches import bp as coaches_bp
from routes.intake import bp as intake_bp
from routes.enrollments import bp as enrollments_bp
from routes.weighins import bp as weighins_bp
from routes.goals import bp as goals_bp
from routes.milestones import bp as milestones_bp
from routes.assignments import bp as assignments_bp
from routes.messaging import bp as messaging_bp
from routes.invoices import bp as invoices_bp
from routes.eligibility import bp as eligibility_bp
from routes.rx import bp as rx_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        programs_bp, plans_bp, members_bp, coaches_bp, intake_bp,
        enrollments_bp, weighins_bp, goals_bp, milestones_bp,
        assignments_bp, messaging_bp, invoices_bp, eligibility_bp, rx_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
