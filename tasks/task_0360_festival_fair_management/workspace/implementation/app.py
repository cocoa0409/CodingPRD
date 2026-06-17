"""Festival & Fair Management API — Flask entry point.

In-memory store, boots empty every time. Validation ordering follows
PRD §3.11 exactly (lower priority number wins).
"""
import os
from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "method not allowed")


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_INVALID_REQUEST", 422, "unexpected error: %s" % e)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------
import routes_festival  # noqa: E402
import routes_structure  # noqa: E402
import routes_tickets  # noqa: E402
import routes_wristbands  # noqa: E402
import routes_vendors  # noqa: E402
import routes_gate_incidents  # noqa: E402

routes_festival.register(app)
routes_structure.register(app)
routes_tickets.register(app)
routes_wristbands.register(app)
routes_vendors.register(app)
routes_gate_incidents.register(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
