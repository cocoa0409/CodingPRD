"""Newborn / Parenting Registry API — entry point.

Wires Flask, the auth middleware (PRD §2.1), global error handlers, and the
route blueprints. The in-memory store starts empty on every boot — see db.py.
Nothing is seeded at startup; tests build all preconditions via the API.
"""

import os

from flask import Flask, request

from errors import APIError
from middleware import extract_identity
from response import err

from routes.system_ops import bp as bp_system_ops
from routes.insurance_policies import bp as bp_insurance_policies
from routes.registrations import bp as bp_registrations
from routes.newborns import bp as bp_newborns
from routes.lactation_consults import bp as bp_lactation_consults
from routes.nicu_beds import bp as bp_nicu_beds
from routes.nicu_stays import bp as bp_nicu_stays
from routes.discharge_bags import bp as bp_discharge_bags
from routes.follow_up_tasks import bp as bp_follow_up_tasks
from routes.dependent_enrollments import bp as bp_dependent_enrollments
from routes.government_filings import bp as bp_government_filings


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _auth():
        if request.method == "OPTIONS":
            return None
        # Unknown path: let the 404 handler emit the envelope.
        if request.url_rule is None:
            return None
        try:
            extract_identity()
        except APIError as e:
            return err(e.error_id, e.message, e.http_status)
        return None

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return err(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found_handler(_e):
        return err("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_e):
        return err("ERR_INVALID_REQUEST", "Method not allowed for this path.", 400)

    @app.errorhandler(400)
    def _bad_request(_e):
        return err("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(Exception)
    def _unhandled(e: Exception):
        if isinstance(e, APIError):
            return err(e.error_id, e.message, e.http_status)
        code = getattr(e, "code", None)
        if isinstance(code, int):
            if code == 404:
                return err("ERR_NOT_FOUND", "Resource not found.", 404)
            if code in (400, 405, 415):
                return err("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return err("ERR_INVALID_REQUEST", "Unhandled server error.", 500)

    app.register_blueprint(bp_system_ops)
    app.register_blueprint(bp_insurance_policies)
    app.register_blueprint(bp_registrations)
    app.register_blueprint(bp_newborns)
    app.register_blueprint(bp_lactation_consults)
    app.register_blueprint(bp_nicu_beds)
    app.register_blueprint(bp_nicu_stays)
    app.register_blueprint(bp_discharge_bags)
    app.register_blueprint(bp_follow_up_tasks)
    app.register_blueprint(bp_dependent_enrollments)
    app.register_blueprint(bp_government_filings)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=False)
