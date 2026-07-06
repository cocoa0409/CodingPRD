"""Virtual Receptionist & Answering Service API — entry point.

In-memory only; state is wiped on every process boot. No seeding at startup.
"""
import os

from flask import Flask

import errors
from response import error_response, success_object
from middleware import get_auth, require_role, ROLE_ADMIN
from common import get_body, as_str
from db import db

from routes.service_plans import bp as service_plans_bp
from routes.accounts import bp as accounts_bp
from routes.call_scripts import bp as call_scripts_bp
from routes.spam_rules import bp as spam_rules_bp
from routes.receptionists import bp as receptionists_bp
from routes.availability_windows import bp as availability_windows_bp
from routes.calendar_slots import bp as calendar_slots_bp
from routes.calls import bp as calls_bp
from routes.messages import bp as messages_bp
from routes.escalations import bp as escalations_bp
from routes.crm_handoffs import bp as crm_handoffs_bp
from routes.appointments import bp as appointments_bp
from routes.billing_periods import bp as billing_periods_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # --- Logical clock endpoint (PRD §2.10) ---------------------------------
    @app.route("/va/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        _, role = get_auth()
        require_role(role, {ROLE_ADMIN})
        body = get_body()
        to_iso = as_str(body, "to_iso8601", required=True)
        try:
            db.clock.set_from_iso(to_iso)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 instant")
        return success_object({
            "current_utc": db.clock.current_iso(),
            "epoch_seconds": db.clock.epoch_seconds(),
            "minute_of_day": db.clock.minute_of_day(),
        }, 200)

    for bp in (
        service_plans_bp, accounts_bp, call_scripts_bp, spam_rules_bp,
        receptionists_bp, availability_windows_bp, calendar_slots_bp,
        calls_bp, messages_bp, escalations_bp, crm_handoffs_bp,
        appointments_bp, billing_periods_bp,
    ):
        app.register_blueprint(bp)

    # --- Error handlers -----------------------------------------------------
    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, errors.ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 422)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
