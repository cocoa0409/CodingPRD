"""Tuition Payment Plan API — entry point, error handlers, route registration.

In-memory only: db.py holds module-level dicts that start empty on every boot.
No seeding. The harness restarts this process before every test.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.institutions import bp as institutions_bp
from routes.terms import bp as terms_bp
from routes.students import bp as students_bp
from routes.plan_templates import bp as plan_templates_bp
from routes.enrollments import bp as enrollments_bp
from routes.installments import bp as installments_bp
from routes.charges import bp as charges_bp
from routes.aids import bp as aids_bp
from routes.payments import bp as payments_bp
from routes.late_fees import bp as late_fees_bp
from routes.holds import bp as holds_bp
from routes.withdrawals import bp as withdrawals_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(institutions_bp)
    app.register_blueprint(terms_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(plan_templates_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(installments_bp)
    app.register_blueprint(charges_bp)
    app.register_blueprint(aids_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(late_fees_bp)
    app.register_blueprint(holds_bp)
    app.register_blueprint(withdrawals_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> ERR_NOT_FOUND in the standard envelope.
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.http_status, exc.message)
        return error_response("ERR_INVALID_REQUEST", 400, "Bad request")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
