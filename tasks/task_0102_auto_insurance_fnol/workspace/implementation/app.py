"""Auto Insurance FNOL API — Flask entry point.

In-memory storage only (see db.py). No entity seeding at startup. Binds
0.0.0.0:$PORT (default 10000) and runs in the foreground via start.sh.
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response

from routes.policies import bp as policies_bp
from routes.adjusters import bp as adjusters_bp
from routes.claims import bp as claims_bp
from routes.claim_parties import bp as claim_parties_bp
from routes.repair_estimates import bp as repair_estimates_bp
from routes.total_loss_evaluations import bp as total_loss_evaluations_bp
from routes.rental_reimbursements import bp as rental_reimbursements_bp
from routes.subrogation_cases import bp as subrogation_cases_bp
from routes.disbursements import bp as disbursements_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (policies_bp, adjusters_bp, claims_bp, claim_parties_bp,
               repair_estimates_bp, total_loss_evaluations_bp,
               rental_reimbursements_bp, subrogation_cases_bp,
               disbursements_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown path/resource. Authenticate first so a missing auth header
        # surfaces as 401, matching the validation precedence (auth before 404).
        from auth import authenticate
        try:
            authenticate()
        except ApiError as ae:
            return error_response(ae.error_id, ae.http_status, ae.message)
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        from auth import authenticate
        try:
            authenticate()
        except ApiError as ae:
            return error_response(ae.error_id, ae.http_status, ae.message)
        return error_response("ERR_NOT_FOUND", 404, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 422, "internal error: %s" % e)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
