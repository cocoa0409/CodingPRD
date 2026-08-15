"""Rail Crew Calling & Hours of Service API — Flask entry point.

Storage is in-memory only and starts empty on every boot; the logical clock
starts at exactly 2026-08-01T00:00:00Z (never wall-clock).
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes.clock import bp as clock_bp
from routes.employees import bp as employees_bp
from routes.boards import bp as boards_bp
from routes.jobs import bp as jobs_bp
from routes.calls import bp as calls_bp
from routes.assignments import bp as assignments_bp
from routes.rest_periods import bp as rest_periods_bp
from routes.leave_bids import bp as leave_bids_bp
from routes.pay_records import bp as pay_records_bp
from routes.shortages import bp as shortages_bp

for bp in (
    clock_bp,
    employees_bp,
    boards_bp,
    jobs_bp,
    calls_bp,
    assignments_bp,
    rest_periods_bp,
    leave_bids_bp,
    pay_records_bp,
    shortages_bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found."))


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found."))


@app.errorhandler(400)
def handle_bad_request(_err):
    return error_response(ApiError(ERR_INVALID_REQUEST, 400, "Bad request."))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError(ERR_INVALID_REQUEST, 500, "Internal error: %s" % err))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
