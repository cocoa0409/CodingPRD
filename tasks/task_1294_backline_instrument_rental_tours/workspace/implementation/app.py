"""Backline Tour Rental API — Flask entry point.

Mounts every resource group under /backline and wires the standard error
envelope (PRD §2.2). Storage is in-memory only; the store starts empty on
every boot and no entity is seeded at startup.
"""

import os
from flask import Flask

import errors as err
from response import error_response
from routes import (clock, artists, tours, stops, rider_lines, gear,
                    reservations, shipments, flight_cases, vendors,
                    maintenance, damage_claims)

app = Flask(__name__)

for module in (clock, artists, tours, stops, rider_lines, gear, reservations,
               shipments, flight_cases, vendors, maintenance, damage_claims):
    app.register_blueprint(module.bp)


@app.errorhandler(err.ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response(err.ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response(err.ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, err.ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response(err.ERR_INVALID_REQUEST, "Invalid request", 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
