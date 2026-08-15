"""Propane Wholesale & Terminal Supply API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError
import response as resp

from routes.ops import bp as ops_bp
from routes.terminals import bp as terminals_bp
from routes.supply import bp as supply_bp
from routes.dealers import bp as dealers_bp
from routes.dealer_contracts import bp as dealer_contracts_bp
from routes.price_indexes import bp as price_indexes_bp
from routes.fleet import bp as fleet_bp
from routes.delivery_orders import bp as delivery_orders_bp
from routes.cold_snaps import bp as cold_snaps_bp
from routes.payments import bp as payments_bp

app = Flask(__name__)
app.json.sort_keys = False

for bp in (
    ops_bp,
    terminals_bp,
    supply_bp,
    dealers_bp,
    dealer_contracts_bp,
    price_indexes_bp,
    fleet_bp,
    delivery_orders_bp,
    cold_snaps_bp,
    payments_bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return resp.error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return resp.error("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return resp.error("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    # Never leak a bare 500 without the envelope.
    return resp.error("ERR_INVALID_REQUEST", 400, f"Malformed request: {e}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
