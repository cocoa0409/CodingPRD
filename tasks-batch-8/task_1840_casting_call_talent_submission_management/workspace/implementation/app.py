"""Casting Call & Talent Submission API — Flask entry point.

In-memory store only; boots empty on every process start (no seeding).
Logical clock starts at exactly 2026-08-01T00:00:00Z (PRD 2.4).
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import productions, rosters, submissions, sessions, holds, offers, permits, bookings

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (productions, rosters, submissions, sessions, holds, offers, permits, bookings):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response("ERR_NOT_FOUND", "Resource does not exist", 404)


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response("ERR_NOT_FOUND", "Resource does not exist", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response("ERR_INVALID_REQUEST", str(err), 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
