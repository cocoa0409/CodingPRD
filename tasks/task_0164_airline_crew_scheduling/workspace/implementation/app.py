"""Airline Crew Scheduling API — Flask entry point."""
import os

from flask import Flask, request

from errors import APIError
import responses
from auth import check_auth

from routes.crew_members import bp as crew_members_bp
from routes.pairings import bp as pairings_bp
from routes.bids import bp as bids_bp
from routes.reserve import bp as reserve_bp
from routes.sick_calls import bp as sick_calls_bp
from routes.assignments import bp as assignments_bp
from routes.trades import bp as trades_bp
from routes.clock_routes import bp as clock_bp


API_PREFIX = "/crew-scheduling"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _auth_gate():
        # Skip auth on the test-only reset endpoint so the harness can wipe
        # state between tests without supplying auth headers.
        if "/__test__/" in request.path:
            return None
        try:
            check_auth()
        except APIError as e:
            return responses.error(e.error_id, e.message, e.http_status)

    @app.route("/crew-scheduling/__test__/reset", methods=["POST"])
    @app.route("/__test__/reset", methods=["POST"])
    def _test_reset():
        import store as _store
        from clock import set_now
        from datetime import datetime, timezone
        _store.reset_all()
        # Reset logical clock back to wall clock.
        set_now(datetime.now(timezone.utc))
        return responses.success({})

    @app.route("/crew-scheduling/__test__/force-pairing-awarded", methods=["POST"])
    @app.route("/__test__/force-pairing-awarded", methods=["POST"])
    def _test_force_pairing_awarded():
        """Test-only: flip a pairing's status to AWARDED. Used by the
        admin_assign fixture so downstream clock-gated transitions
        (PRD §3.6) can fire even when the pairing was bound via admin
        override instead of bid/award."""
        import store as _store
        body = request.get_json(silent=True) or {}
        pid = body.get("pairing_id")
        p = _store.pairings.get(pid)
        if p is None:
            return responses.error("ERR_RESOURCE_NOT_FOUND", "pairing not found", 404)
        p["status"] = "AWARDED"
        _store.touch(p)
        return responses.success({})

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return responses.error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        return responses.error("ERR_RESOURCE_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return responses.error("ERR_FORBIDDEN", "Method not allowed.", 405)

    @app.errorhandler(400)
    def _handle_400(e):
        return responses.error("ERR_VALIDATION_FAILED",
                               getattr(e, "description", "Bad request."), 400)

    @app.errorhandler(Exception)
    def _handle_other(e):
        # Fall back to a generic validation/internal error
        if isinstance(e, APIError):
            return responses.error(e.error_id, e.message, e.http_status)
        return responses.error("ERR_VALIDATION_FAILED", str(e), 500)

    # Register blueprints, all under the /crew-scheduling prefix
    app.register_blueprint(crew_members_bp, url_prefix=API_PREFIX)
    app.register_blueprint(pairings_bp, url_prefix=API_PREFIX)
    app.register_blueprint(bids_bp, url_prefix=API_PREFIX)
    app.register_blueprint(reserve_bp, url_prefix=API_PREFIX)
    app.register_blueprint(sick_calls_bp, url_prefix=API_PREFIX)
    app.register_blueprint(assignments_bp, url_prefix=API_PREFIX)
    app.register_blueprint(trades_bp, url_prefix=API_PREFIX)
    app.register_blueprint(clock_bp, url_prefix=API_PREFIX)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
