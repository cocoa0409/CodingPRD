"""Parametric Index Insurance API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store is in-memory only and starts
empty on every boot; per-test-server isolation restarts this process before
every test.
"""

import os

from flask import Flask

from errors import ApiError, err, ERR_INVALID_REQUEST
from response import error_response

app = Flask(__name__)

# Register blueprints
from routes.clock import bp as clock_bp
from routes.programs import bp as programs_bp
from routes.indexes import bp as indexes_bp
from routes.stations import bp as stations_bp
from routes.observations import bp as observations_bp
from routes.policyholders import bp as policyholders_bp
from routes.policies import bp as policies_bp
from routes.invoices import bp as invoices_bp
from routes.trigger_events import bp as trigger_events_bp
from routes.claims import bp as claims_bp
from routes.disputes import bp as disputes_bp
from routes.treaties import bp as treaties_bp

for bp in (
    clock_bp, programs_bp, indexes_bp, stations_bp, observations_bp,
    policyholders_bp, policies_bp, invoices_bp, trigger_events_bp,
    claims_bp, disputes_bp, treaties_bp,
):
    app.register_blueprint(bp)


# ---------------------------------------------------------------------------
# Error handlers — all errors use the PRD §2.2 error envelope
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(e: ApiError):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ERR_INVALID_REQUEST, "Not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)


@app.errorhandler(500)
def handle_500(e):
    return error_response(ERR_INVALID_REQUEST, "Internal server error", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
