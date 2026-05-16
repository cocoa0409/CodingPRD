"""Flask application entry point for the Medicare Advantage Enrollment API."""
import os
import traceback

from flask import Flask, request

from auth import auth_middleware
from errors import APIError, err
from response import error_response

from routes.beneficiaries import bp as beneficiaries_bp
from routes.plans import bp as plans_bp
from routes.enrollment_periods import bp as enrollment_periods_bp
from routes.enrollments import bp as enrollments_bp, lep_bp
from routes.medigap import bp as medigap_bp
from routes.drug_claims import bp as drug_claims_bp, ledger_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Don't sort keys — preserve insertion order for stable response shapes.
    app.json.sort_keys = False

    # ---- global before-request: auth (priority 1, 2) ----
    @app.before_request
    def _global_auth():
        # 404 for nonexistent paths should still fall through, but auth should run first
        # so that the validation priority order is honoured.
        # If the request didn't match any route, Flask raises 404 after this hook anyway.
        try:
            auth_middleware()
        except APIError as e:
            return error_response(e.error_id, e.message, e.http_status)

    # ---- error handlers ----
    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def _handle_400(e):
        return error_response("ERR_VALIDATION", "Bad request", 422)

    @app.errorhandler(Exception)
    def _handle_unhandled(e):
        # Fallback for unexpected errors. Log to stderr.
        traceback.print_exc()
        return error_response("ERR_VALIDATION", f"Internal error: {e}", 422)

    # ---- register blueprints ----
    app.register_blueprint(clock_bp)
    app.register_blueprint(beneficiaries_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(enrollment_periods_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(lep_bp)
    app.register_blueprint(medigap_bp)
    app.register_blueprint(drug_claims_bp)
    app.register_blueprint(ledger_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
