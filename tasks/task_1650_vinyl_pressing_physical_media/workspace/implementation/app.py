"""Vinyl Pressing API — Flask entry point.

In-memory only; the store starts empty on every boot. All entity state is
built through the API surface.
"""

import os
from datetime import datetime, timezone

from flask import Flask, request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
from middleware import get_auth, require_role
from response import success_object, error_response

from routes.customers import bp as customers_bp
from routes.releases import bp as releases_bp
from routes.press_orders import bp as press_orders_bp
from routes.tooling import bp as tooling_bp
from routes.test_pressings import bp as test_pressings_bp
from routes.print_jobs import bp as print_jobs_bp
from routes.press_lines import bp as press_lines_bp
from routes.qc import bp as qc_bp
from routes.inventory import bp as inventory_bp
from routes.shipments import bp as shipments_bp
from routes.invoices import bp as invoices_bp

app = Flask(__name__)

for bp in (
    customers_bp, releases_bp, press_orders_bp, tooling_bp, test_pressings_bp,
    print_jobs_bp, press_lines_bp, qc_bp, inventory_bp, shipments_bp,
    invoices_bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError(ERR_INVALID_REQUEST, "Unknown route", 404))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError(ERR_INVALID_REQUEST, "Method not allowed", 405))


@app.errorhandler(500)
def handle_500(err):
    return error_response(ApiError(ERR_INVALID_REQUEST, "Internal server error", 500))


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_auth()
    require_role(role, ["PlatformAdmin"])
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str) or not to_iso:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 is required", 400)
    try:
        parsed = datetime.fromisoformat(to_iso.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp", 400)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    db.set_logical_clock(parsed.astimezone(timezone.utc))
    return success_object({})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
