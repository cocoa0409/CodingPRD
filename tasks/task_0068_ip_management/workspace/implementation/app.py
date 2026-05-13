"""Flask app entry point — IP Management API."""
import os
import logging
from flask import Flask, request, g

from errors import APIError, ERR_UNAUTHENTICATED, ERR_BAD_REQUEST, ERR_NOT_FOUND
from response import error_response
from middleware import extract_identity

# Route blueprints
from routes.business_units import bp as bp_bu
from routes.agents import bp as bp_agents
from routes.ip_rights import bp as bp_ipr
from routes.annual_fees import bp as bp_fees
from routes.contracts import bp as bp_contracts
from routes.protection_cases import bp as bp_cases
from routes.costs import bp as bp_costs
from routes.audit import bp as bp_audit
from routes.system import bp as bp_system


def create_app():
    app = Flask(__name__)
    app.config["PROPAGATE_EXCEPTIONS"] = False

    # JSON-mode 404 handler
    @app.errorhandler(404)
    def _not_found(e):
        return error_response(ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(APIError)
    def _api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(Exception)
    def _unhandled(e):
        logging.exception("Unhandled exception")
        # Fall back to a structured 500 response in our envelope.
        return error_response("ERR_INTERNAL", str(e), 500)

    @app.before_request
    def _auth_gate():
        # Skip auth gate for _health (per PRD §2.1)
        path = request.path
        if path == "/_health":
            return
        # Auth is enforced by per-route decorators, but pre-emptive auth check here
        # avoids surprises if a route lacks the decorator.
        # However, we MUST allow per-route role checks to be the final word, so
        # we only validate header presence here. We let require_roles handle role checks.
        try:
            extract_identity()
        except APIError as exc:
            return error_response(exc.error_id, exc.message, exc.http_status)

    # Register blueprints
    app.register_blueprint(bp_bu)
    app.register_blueprint(bp_agents)
    app.register_blueprint(bp_ipr)
    app.register_blueprint(bp_fees)
    app.register_blueprint(bp_contracts)
    app.register_blueprint(bp_cases)
    app.register_blueprint(bp_costs)
    app.register_blueprint(bp_audit)
    app.register_blueprint(bp_system)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
