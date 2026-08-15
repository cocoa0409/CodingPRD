"""Community Composting Drop-Off Program API — Flask entry point."""

import os

from flask import Flask

import errors
from errors import ApiError
from response import error_response
from routes import (
    clock, programs, sites, agreements, materials, participants,
    drops, contamination, routes_stops, distributions, complaints,
    diversion,
)

app = Flask(__name__)

for bp in (
    clock.bp,
    programs.bp,
    sites.bp,
    agreements.bp,
    materials.bp,
    participants.bp,
    drops.bp,
    contamination.bp,
    routes_stops.bp,
    distributions.bp,
    complaints.bp,
    diversion.bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response(ApiError(
        errors.ERR_NOT_FOUND, "Resource not found", 404,
    ))


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response(ApiError(
        errors.ERR_NOT_FOUND, "Resource not found", 404,
    ))


@app.errorhandler(400)
def handle_bad_request(e):
    return error_response(ApiError(
        errors.ERR_INVALID_REQUEST, "Malformed request", 400,
    ))


@app.errorhandler(500)
def handle_internal_error(e):
    return error_response(ApiError(
        errors.ERR_INVALID_REQUEST, "Internal server error", 500,
    ))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
