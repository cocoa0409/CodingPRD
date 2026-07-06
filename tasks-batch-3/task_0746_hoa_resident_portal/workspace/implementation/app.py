"""Flask app entrypoint for the HOA Resident Portal API.
No entity seeding at startup — the harness kills/re-launches the server between
tests and PRD §2.9 says the logical clock defaults to 2026-03-01T00:00:00Z."""

import os
from datetime import datetime, timezone

from flask import Flask, g, request

import db  # noqa: F401  — imported for side-effect (module-level state is the store)
from response import error, success
from errors import ApiError
from utils import new_request_id
from auth import get_user

# Blueprint imports
from routes.homeowners import bp as homeowners_bp
from routes.properties import bp as properties_bp
from routes.assessments import bp as assessments_bp
from routes.payments import bp as payments_bp
from routes.arc import bp as arc_bp
from routes.violations import bp as violations_bp
from routes.amenities import bp as amenities_bp
from routes.reservations import bp as reservations_bp
from routes.motions import bp as motions_bp
from routes.ballots import bp as ballots_bp
from routes.work_orders import bp as work_orders_bp
from routes.documents import bp as documents_bp
from routes.admin import bp as admin_bp


def _now_iso():
    dt = datetime.now(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def create_app():
    app = Flask(__name__)
    # Disable Flask's ordering of JSON keys (preserve insertion order).
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False  # Flask 2.3+
    except Exception:
        pass

    @app.before_request
    def _stamp_request():
        g.req_id = new_request_id()
        g.req_timestamp = _now_iso()

    # Register blueprints
    app.register_blueprint(homeowners_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(assessments_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(arc_bp)
    app.register_blueprint(violations_bp)
    app.register_blueprint(amenities_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(motions_bp)
    app.register_blueprint(ballots_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def _handle_route_404(e):
        # Route doesn't exist — must still authenticate first per priority ordering.
        try:
            get_user()
        except ApiError as api_e:
            return error(api_e.error_id, api_e.http_status, api_e.message)
        return error("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _handle_method_not_allowed(e):
        try:
            get_user()
        except ApiError as api_e:
            return error(api_e.error_id, api_e.http_status, api_e.message)
        return error("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(400)
    def _handle_400(e):
        return error("ERR_INVALID_REQUEST", 400, "Malformed request")

    @app.errorhandler(Exception)
    def _handle_unknown(e):
        if isinstance(e, ApiError):
            return error(e.error_id, e.http_status, e.message)
        # Unhandled — return a generic 500. Should not happen in tests.
        return error("ERR_INVALID_REQUEST", 500, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Disable the reloader so start.sh remains foreground and PID-stable.
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
