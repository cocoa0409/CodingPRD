"""Disaster Relief & FEMA Case Management API — entry point."""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response

from routes.clock import bp as clock_bp
from routes.declarations import bp as declarations_bp
from routes.inspectors import bp as inspectors_bp
from routes.caseworkers import bp as caseworkers_bp
from routes.applicants import bp as applicants_bp
from routes.assessments import bp as assessments_bp
from routes.ihp_cases import bp as ihp_cases_bp
from routes.award_line_items import bp as award_line_items_bp
from routes.dob_records import bp as dob_records_bp
from routes.appeals import bp as appeals_bp
from routes.sba_referrals import bp as sba_referrals_bp
from routes.disbursements import bp as disbursements_bp
from routes.recoupments import bp as recoupments_bp
from routes.rental_periods import bp as rental_periods_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp, declarations_bp, inspectors_bp, caseworkers_bp, applicants_bp,
        assessments_bp, ihp_cases_bp, award_line_items_bp, dob_records_bp,
        appeals_bp, sba_referrals_bp, disbursements_bp, recoupments_bp,
        rental_periods_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_response("ERR_INVALID_REQUEST", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)

    @app.errorhandler(400)
    def handle_400(_e):
        return error_response("ERR_INVALID_REQUEST", "Bad request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        import traceback
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", "Internal error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
