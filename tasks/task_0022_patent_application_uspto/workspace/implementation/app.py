"""USPTO Patent Prosecution API — Flask entry point."""

import os
import sys
from flask import Flask

from errors import APIError
from response import error as error_response

# Route blueprints
from routes.applicants import bp as applicants_bp
from routes.applications import bp as applications_bp
from routes.office_actions import bp as office_actions_bp
from routes.office_action_responses import bp as office_action_responses_bp
from routes.maintenance_fees import bp as maintenance_fees_bp
from routes.fee_payments import bp as fee_payments_bp
from routes.pct_phase_entries import bp as pct_phase_entries_bp
from routes.system import bp as system_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Preserve insertion order in JSON responses
    app.json.sort_keys = False

    app.register_blueprint(applicants_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(office_actions_bp)
    app.register_blueprint(office_action_responses_bp)
    app.register_blueprint(maintenance_fees_bp)
    app.register_blueprint(fee_payments_bp)
    app.register_blueprint(pct_phase_entries_bp)
    app.register_blueprint(system_bp)

    @app.errorhandler(APIError)
    def handle_api_error(exc: APIError):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_response("ERR_APPLICATION_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response(
            "ERR_APPLICATION_NOT_FOUND", 404, "Method not allowed"
        )

    @app.errorhandler(400)
    def handle_400(_e):
        return error_response("ERR_INVALID_REQUEST", 400, "Bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(e: Exception):
        # Log but never leak details
        print(f"[unhandled] {type(e).__name__}: {e}", file=sys.stderr)
        return error_response(
            "ERR_INVALID_REQUEST",
            400,
            f"Unexpected error: {type(e).__name__}",
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
