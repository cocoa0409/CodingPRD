"""Community Center Program Registration & Operations API (PRD benchmark task).

Flask entry point: blueprint registration and error handlers.  The store is
in-memory and starts empty on every boot; the logical clock starts at
2026-08-01T00:00:00Z (PRD 2.5).
"""
import os

from flask import Flask

from errors import ApiError
from util import error_response
from routes import (
    attendance,
    clock_routes,
    contracts,
    households,
    instructors,
    meetings,
    participants,
    payments,
    programs,
    registrations,
    rooms,
    safety_forms,
    scholarships,
    seasons,
    sessions,
)

app = Flask(__name__)

for module in (
    clock_routes,
    seasons,
    programs,
    rooms,
    instructors,
    sessions,
    meetings,
    contracts,
    households,
    participants,
    safety_forms,
    scholarships,
    registrations,
    payments,
    attendance,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response(ApiError("ERR_NOT_FOUND", "Method not allowed", 405))


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response(ApiError("ERR_INTERNAL", "Unexpected server error: %s" % err, 500))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
