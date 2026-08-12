"""Timber Sale & Forest Management Plan API — entry point.

In-memory storage only; the store starts empty on every boot. The logical
clock starts at exactly 2026-05-01T00:00:00Z and never uses wall-clock time.
"""
import os

from flask import Flask

from core import ApiError, error_response

app = Flask(__name__)

import routes_party
import routes_tracts
import routes_cruises
import routes_prescriptions
import routes_sales
import routes_contracts
import routes_tickets
import routes_settlements
import routes_inspections
import routes_reforestation
import routes_carbon

for mod in (routes_party, routes_tracts, routes_cruises, routes_prescriptions,
            routes_sales, routes_contracts, routes_tickets, routes_settlements,
            routes_inspections, routes_reforestation, routes_carbon):
    app.register_blueprint(mod.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError("ERR_INVALID_REQUEST", 404,
                                   "route not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError("ERR_INVALID_REQUEST", 405,
                                   "method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INVALID_REQUEST", 500, str(e)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
