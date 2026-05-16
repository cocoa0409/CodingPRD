"""NCAA Recruiting and NIL Compliance API — Flask entry point.

Listens on PORT env (default 10000), binds 0.0.0.0.
"""

import os
import traceback

from flask import Flask, request

from core.errors import APIError
from core.envelope import error_response
from core.auth import parse_auth

from routes.system import bp as system_bp
from routes.programs import bp as programs_bp
from routes.recruiting_calendars import bp as calendars_bp
from routes.athletes import bp as athletes_bp
from routes.eligibility_records import bp as eligibility_bp
from routes.scholarship_slots import bp as slots_bp
from routes.recruiting_contacts import bp as contacts_bp
from routes.nil_deals import bp as nil_deals_bp
from routes.transfer_portal import bp as portal_bp
from routes.violations import bp as violations_bp


def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TRAP_HTTP_EXCEPTIONS"] = False

    @app.before_request
    def _auth_gate():
        if request.method == "OPTIONS":
            return None
        parse_auth()
        return None

    @app.errorhandler(APIError)
    def _api_err(e):
        return error_response(e)

    @app.errorhandler(404)
    def _not_found(_e):
        return error_response(APIError("ERR_NOT_FOUND", "Resource not found", 404))

    @app.errorhandler(405)
    def _method(_e):
        return error_response(APIError("ERR_VALIDATION_FAILED", "Method not allowed", 400))

    @app.errorhandler(400)
    def _bad_req(_e):
        return error_response(APIError("ERR_VALIDATION_FAILED", "Bad request", 400))

    @app.errorhandler(Exception)
    def _unhandled(e):
        traceback.print_exc()
        if isinstance(e, APIError):
            return error_response(e)
        return error_response(APIError("ERR_VALIDATION_FAILED", str(e) or "Internal error", 400))

    # Register blueprints
    app.register_blueprint(system_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(calendars_bp)
    app.register_blueprint(athletes_bp)
    app.register_blueprint(eligibility_bp)
    app.register_blueprint(slots_bp)
    app.register_blueprint(contacts_bp)
    app.register_blueprint(nil_deals_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(violations_bp)
    return app


app = _build_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
