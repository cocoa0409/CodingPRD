"""Interfacility Transfer & Bed Placement API.

Entry point: blueprint registration, the before_request chain that applies
rungs 1-2 of the validation ladder (PRD 2.8) plus the lazy bed-hold expiry
sweep (PRD 3.4), and the single error handler that renders the section 2.2
error envelope.  Storage is in-memory only; nothing is seeded at startup -
the store is empty on every boot.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request  # noqa: E402

from core.authz import check_user_context, authorize  # noqa: E402
from core.envelope import error_response  # noqa: E402
from core.errors import ApiError  # noqa: E402
from core import domain  # noqa: E402
from routes import cases, clock_ops, holds, insurance, packets, records  # noqa: E402
from routes import refdata, transport  # noqa: E402

BLUEPRINTS = (
    clock_ops.bp,
    refdata.bp,
    cases.bp,
    holds.bp,
    transport.bp,
    insurance.bp,
    packets.bp,
    records.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def validation_ladder_head():
        # Rung 1: user context.  Rung 2: role authorization.
        check_user_context()
        authorize()
        # Lazy bed-hold expiry: every read or write that touches holds sees the
        # clock's current position reflected first.  The clock endpoint itself
        # is exempt - moving the clock eagerly rewrites nothing (PRD 2.4).
        if request.path != "/_clock/set_current_utc":
            domain.sweep_hold_expiries()

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(500)
    def handle_internal_error(exc):
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
