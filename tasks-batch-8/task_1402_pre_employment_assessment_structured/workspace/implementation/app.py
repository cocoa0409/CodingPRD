"""Pre-Employment Assessment API — Flask entry point.
Mounts all /talent routes and installs the error-envelope handlers."""
import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes import (accommodations, assessments, candidates, cycles, decisions,
                    guides, instruments, interviewers, requisitions, retention,
                    scorecards, sessions, snapshots, vendors)

for module in (vendors, instruments, guides, requisitions, cycles, candidates,
               assessments, accommodations, interviewers, sessions, scorecards,
               decisions, snapshots, retention):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(400)
def handle_400(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INVALID_REQUEST", "Malformed request", 400))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    app.logger.exception("Unexpected error: %s", err)
    return error_response(ApiError("ERR_INVALID_REQUEST", "Unexpected server error", 400))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
