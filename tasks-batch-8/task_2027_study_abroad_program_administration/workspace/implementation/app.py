"""Study Abroad Program Administration API -- Flask entry point."""

import os
from flask import Flask
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.partner_agreements import bp as partner_agreements_bp
from routes.programs import bp as programs_bp
from routes.students import bp as students_bp
from routes.applications import bp as applications_bp
from routes.course_preapprovals import bp as course_preapprovals_bp
from routes.travel_advisories import bp as travel_advisories_bp
from routes.insurance_enrollments import bp as insurance_enrollments_bp
from routes.billing_statements import bp as billing_statements_bp
from routes.incidents import bp as incidents_bp
from routes.credit_postings import bp as credit_postings_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(partner_agreements_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(course_preapprovals_bp)
    app.register_blueprint(travel_advisories_bp)
    app.register_blueprint(insurance_enrollments_bp)
    app.register_blueprint(billing_statements_bp)
    app.register_blueprint(incidents_bp)
    app.register_blueprint(credit_postings_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Let ApiError pass through via its own handler; everything else is a 400
        if isinstance(err, ApiError):
            return handle_api_error(err)
        return error_response(ERR_INVALID_REQUEST, str(err), 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
