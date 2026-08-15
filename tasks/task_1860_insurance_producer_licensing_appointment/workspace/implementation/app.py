"""Insurance Producer Licensing & Appointment Management API.

Entry point: route registration and the error handlers that render the
PRD section 2.2 error envelope.  Storage is in-memory only; nothing is seeded
at startup - the store is empty on every boot and the logical clock starts at
exactly 2026-08-01T00:00:00Z (never wall-clock time).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402

from core.envelope import error_response  # noqa: E402
from core.errors import ApiError  # noqa: E402
from routes import (  # noqa: E402
    agencies, applications, appointments, ce_credits, commissions,
    inquiries, licenses, ops, producers, regulatory_actions,
)

BLUEPRINTS = (
    agencies.bp,
    producers.bp,
    licenses.bp,
    ce_credits.bp,
    appointments.bp,
    applications.bp,
    commissions.bp,
    regulatory_actions.bp,
    inquiries.bp,
    ops.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
