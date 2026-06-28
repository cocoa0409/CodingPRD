"""Youth Org & Troop Management API — Flask entry point.

In-memory store, fresh on every boot (no seeding). See PRD.md for the contract.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from middleware import authenticate

# Route blueprints.
from routes.councils import bp as councils_bp, clock_bp
from routes.troops import bp as troops_bp
from routes.members import bp as members_bp
from routes.dues import bp as dues_bp, payments_bp
from routes.leader_credentials import bp as leader_credentials_bp
from routes.advancements import bp as advancements_bp
from routes.events import bp as events_bp, reg_bp as event_registrations_bp
from routes.fundraisers import (
    bp as fundraisers_bp,
    orders_bp as fundraiser_orders_bp,
    booth_bp as booth_reservations_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        councils_bp,
        clock_bp,
        troops_bp,
        members_bp,
        dues_bp,
        payments_bp,
        leader_credentials_bp,
        advancements_bp,
        events_bp,
        event_registrations_bp,
        fundraisers_bp,
        fundraiser_orders_bp,
        booth_reservations_bp,
    ):
        app.register_blueprint(bp)

    # ---- Error handling ----
    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        # Unknown route: still authenticate first so unauthenticated callers get
        # 401, otherwise report not-found.
        try:
            authenticate()
        except ApiError as e:
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        try:
            authenticate()
        except ApiError as e:
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        # Surface unexpected errors as a generic 500 in the standard envelope.
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
