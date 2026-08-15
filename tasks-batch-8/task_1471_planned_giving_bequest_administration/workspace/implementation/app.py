"""Planned Giving & Bequest Administration API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding beyond the
PRD-mandated ReserveFund singleton). All time behavior runs on the logical
clock (2026-08-01T00:00:00Z at startup), never wall-clock time.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask

import store
from envelope import error_response
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

from routes import (  # noqa: E402
    agreements,
    assets,
    clock,
    designations,
    donors,
    estates,
    funds,
    illustrations,
    milestones,
    payments,
    rate_tables,
    reserve,
    valuations,
)

for module in (
    clock,
    donors,
    rate_tables,
    illustrations,
    agreements,
    designations,
    assets,
    payments,
    reserve,
    estates,
    milestones,
    funds,
    valuations,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.status, err.message)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response("ERR_NOT_FOUND", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.status, err.message)
    return error_response("ERR_INVALID_REQUEST", 500, "Internal server error")


# PRD 2.8: the ReserveFund singleton is instantiated at server startup with
# balance_cents=0 and posture=SOLVENT. No other entity is seeded.
store.init_reserve_fund()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
