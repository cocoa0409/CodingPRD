"""Background Check / FCRA Flask app — entry point.

Boots cleanly with empty in-memory state. No entities are seeded at startup.
"""

import os
import sys
from flask import Flask

from errors import APIError
from response import error as error_response

# Route blueprints
from routes.jurisdictions import bp as jurisdictions_bp
from routes.applicants import bp as applicants_bp
from routes.applications import bp as applications_bp
from routes.consents import bp as consents_bp
from routes.orders import bp as orders_bp
from routes.verifications import bp as verifications_bp
from routes.adverse_actions import bp as adverse_actions_bp
from routes.audit_logs import bp as audit_logs_bp
from routes.system_clock import bp as system_clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False

    app.register_blueprint(jurisdictions_bp)
    app.register_blueprint(applicants_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(consents_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(verifications_bp)
    app.register_blueprint(adverse_actions_bp)
    app.register_blueprint(audit_logs_bp)
    app.register_blueprint(system_clock_bp)

    @app.errorhandler(APIError)
    def handle_api_error(exc: APIError):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_response("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(400)
    def handle_400(_e):
        return error_response("ERR_INVALID_REQUEST", 400, "Bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(e: Exception):
        print(f"[unhandled] {type(e).__name__}: {e}", file=sys.stderr)
        return error_response(
            "ERR_INVALID_REQUEST", 400, f"Unexpected error: {type(e).__name__}",
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
