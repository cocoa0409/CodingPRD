"""Glider Club Soaring API — entry point.

Flask app with envelope-consistent error handlers. The store is in-memory
(db.py); nothing is seeded at startup — every entity is created through the
declared API surface.
"""

import os

from flask import Flask

from errors import ApiError, ERR_RESOURCE_NOT_FOUND
from response import error_response

app = Flask(__name__)

from routes.aircraft import bp as aircraft_bp
from routes.availability import bp as availability_bp
from routes.clockops import bp as clockops_bp
from routes.duty import bp as duty_bp
from routes.flights import bp as flights_bp
from routes.members import bp as members_bp
from routes.opsday import bp as opsday_bp
from routes.progress import bp as progress_bp
from routes.reservations import bp as reservations_bp
from routes.retrieves import bp as retrieves_bp
from routes.tiers import bp as tiers_bp
from routes.towslots import bp as towslots_bp

for blueprint in (
    clockops_bp,
    tiers_bp,
    members_bp,
    aircraft_bp,
    availability_bp,
    reservations_bp,
    towslots_bp,
    flights_bp,
    duty_bp,
    progress_bp,
    retrieves_bp,
    opsday_bp,
):
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response(
        ERR_RESOURCE_NOT_FOUND, "The requested resource does not exist", 404
    )


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response(
        ERR_RESOURCE_NOT_FOUND, "Method not allowed for this resource", 405
    )


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", "Internal server error: %s" % err, 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
