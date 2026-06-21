"""NCAA Recruiting & NIL Compliance API — entry point.

Wires Flask, the auth middleware, the global error handlers, and the route
blueprints. The in-memory store starts empty on every boot — see db.py.
"""

import os

from flask import Flask, request

import db
from errors import APIError, invalid_request, unauthenticated
from middleware import extract_identity
from response import err

# Route blueprints
from routes.programs import bp as bp_programs
from routes.student_athletes import bp as bp_student_athletes
from routes.eligibility import bp as bp_eligibility
from routes.recruiting_contacts import bp as bp_recruiting_contacts
from routes.scholarship_offers import bp as bp_scholarship_offers
from routes.nil_deals import bp as bp_nil_deals
from routes.transfer_portal import bp as bp_transfer_portal
from routes.booster_incidents import bp as bp_booster_incidents
from routes.system_ops import bp as bp_system_ops


def create_app() -> Flask:
    app = Flask(__name__)
    # We always serialize via jsonify for the standard envelope, so disable
    # Flask's JSON pretty-printing and key sorting for compact responses.
    app.config["JSON_SORT_KEYS"] = False

    # ---- Global before/after hooks ---------------------------------------
    @app.before_request
    def _auth_and_setup():
        # Skip auth on OPTIONS preflight (Flask handles routing only).
        if request.method == "OPTIONS":
            return None
        # All routes require auth headers. We let Flask resolve the route
        # first by inspecting the URL rule on this request; if there's no
        # matching rule, the standard 404 handler runs (handled below).
        if request.url_rule is None:
            return None
        try:
            extract_identity()
        except APIError as e:
            return err(e.error_id, e.message, e.http_status)
        return None

    # ---- Error handlers --------------------------------------------------
    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return err(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found_handler(_e):
        # Path not registered. We still emit the envelope shape.
        return err("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_e):
        return err("ERR_INVALID_REQUEST", "Method not allowed for this path.", 400)

    @app.errorhandler(400)
    def _bad_request(_e):
        return err("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(Exception)
    def _unhandled(e: Exception):
        # Bubble HTTP exceptions through Flask's default machinery for known
        # status codes; for any unexpected exception, fall back to a 500
        # using the standard error envelope.
        if isinstance(e, APIError):
            return err(e.error_id, e.message, e.http_status)
        # Flask's HTTPException subclasses have .code
        code = getattr(e, "code", None)
        if isinstance(code, int):
            if code == 404:
                return err("ERR_NOT_FOUND", "Resource not found.", 404)
            if code in (400, 405, 415):
                return err("ERR_INVALID_REQUEST", "Malformed request.", 400)
        # Last-resort: surface as INVALID_REQUEST so clients can still parse
        # the envelope. Avoid leaking internal traceback text.
        return err("ERR_INVALID_REQUEST", "Unhandled server error.", 500)

    # ---- Register blueprints --------------------------------------------
    app.register_blueprint(bp_programs)
    app.register_blueprint(bp_student_athletes)
    app.register_blueprint(bp_eligibility)
    app.register_blueprint(bp_recruiting_contacts)
    app.register_blueprint(bp_scholarship_offers)
    app.register_blueprint(bp_nil_deals)
    app.register_blueprint(bp_transfer_portal)
    app.register_blueprint(bp_booster_incidents)
    app.register_blueprint(bp_system_ops)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # threaded=False avoids surprising concurrency on the in-memory store;
    # per-test isolation gives us a fresh process per test anyway.
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=False)
