"""Co-Living By-The-Room Rental API — Flask entry point."""
import os

from flask import Flask, g, request

import helpers
from helpers import ApiError, ROLES, err_body

import routes_core
import routes_applications
import routes_memberships
import routes_billing
import routes_incidents
import routes_maintenance
import routes_payouts


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def authenticate():
        # Priority 1: header authentication (ERR_UNAUTHENTICATED)
        uid = request.headers.get("X-User-ID")
        role = request.headers.get("X-User-Role")
        if not uid or not role or role not in ROLES:
            e = ApiError("ERR_UNAUTHENTICATED",
                         "missing or invalid authentication headers")
            return err_body(e.error_id, e.message), e.http
        g.user_id = uid
        g.role = role

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_body(e.error_id, e.message), e.http

    @app.errorhandler(404)
    def not_found(e):
        return err_body("ERR_INVALID_REQUEST", "resource not found"), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return err_body("ERR_INVALID_REQUEST", "method not allowed"), 405

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return err_body(e.error_id, e.message), e.http
        return err_body("ERR_INVALID_REQUEST", "unexpected error: %s" % e), 400

    for mod in (routes_core, routes_applications, routes_memberships,
                routes_billing, routes_incidents, routes_maintenance,
                routes_payouts):
        app.register_blueprint(mod.bp)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
