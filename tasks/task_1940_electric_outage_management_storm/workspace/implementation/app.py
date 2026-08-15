"""Entry point: Flask app, error handlers, route registration.

Boots cleanly from a fresh process on every invocation. Storage is in-memory
only (db.py) and starts empty — no seeding, no persistence, no /tmp cache.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from middleware import get_context

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Error handlers — the standard error envelope.
# ---------------------------------------------------------------------------


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed")


@app.errorhandler(400)
def handle_400(err):
    return error_response("ERR_INVALID_REQUEST", 400, "Bad request")


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.http_status, err.message)
    import traceback
    traceback.print_exc()
    return error_response("ERR_INVALID_REQUEST", 500, f"Internal error: {err}")


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------
from routes.clock import bp as clock_bp
from routes.storm_events import bp as storm_events_bp
from routes.feeders import bp as feeders_bp
from routes.priority_customers import bp as priority_customers_bp
from routes.trouble_signals import bp as trouble_signals_bp
from routes.outages import bp as outages_bp
from routes.damage_assessments import bp as damage_assessments_bp
from routes.crews import bp as crews_bp
from routes.mutual_aid import bp as mutual_aid_bp
from routes.lodging import bp as lodging_bp
from routes.work_orders import bp as work_orders_bp
from routes.switching_orders import bp as switching_orders_bp
from routes.materials import bp as materials_bp
from routes.ledger import bp as ledger_bp
from routes.fema import bp as fema_bp

for bp in (
    clock_bp, storm_events_bp, feeders_bp, priority_customers_bp,
    trouble_signals_bp, outages_bp, damage_assessments_bp, crews_bp,
    mutual_aid_bp, lodging_bp, work_orders_bp, switching_orders_bp,
    materials_bp, ledger_bp, fema_bp,
):
    app.register_blueprint(bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
