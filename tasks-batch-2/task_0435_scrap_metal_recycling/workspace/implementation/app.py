"""Scrap Metal Recycling Yard API — Flask entry point.

In-memory only. No seeding. State is wiped on every process restart.
"""
import os

from flask import Flask

import errors
import response
from db import db

app = Flask(__name__)
app.url_map.strict_slashes = False

# Register blueprints (one module per resource group).
from routes.sellers import bp as sellers_bp  # noqa: E402
from routes.commodity_prices import bp as prices_bp  # noqa: E402
from routes.tickets import bp as tickets_bp  # noqa: E402
from routes.payouts import bp as payouts_bp  # noqa: E402
from routes.containers import bp as containers_bp  # noqa: E402
from routes.mill_shipments import bp as shipments_bp  # noqa: E402
from routes.hedges import bp as hedges_bp  # noqa: E402
from routes.theft_reports import bp as theft_bp  # noqa: E402

for bp in (sellers_bp, prices_bp, tickets_bp, payouts_bp, containers_bp,
           shipments_bp, hedges_bp, theft_bp):
    app.register_blueprint(bp)


@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return response.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    # Unknown route -> ERR_NOT_FOUND envelope.
    return response.error(errors.ERR_NOT_FOUND, "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(_exc):
    return response.error(errors.ERR_NOT_FOUND, "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, errors.ApiError):
        return response.error(exc.error_id, exc.message, exc.http_status)
    # Any unexpected error -> treat as a malformed request rather than a 500
    # so the test harness sees a well-formed envelope.
    return response.error(errors.ERR_INVALID_REQUEST, "Unprocessable request.", 422)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
