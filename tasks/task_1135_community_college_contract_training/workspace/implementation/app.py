"""Community College Contract Training API — Flask entry point.

Mounts all /ct routes, installs the error-envelope handlers, and serves on
0.0.0.0:$PORT (default 10000). The store starts empty on every boot.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes import agreements, billing, cohorts, commercial, grants, instructors_venues, sessions  # noqa: E402

app.register_blueprint(commercial.bp)
app.register_blueprint(agreements.bp)
app.register_blueprint(grants.bp)
app.register_blueprint(instructors_venues.bp)
app.register_blueprint(cohorts.bp)
app.register_blueprint(sessions.bp)
app.register_blueprint(billing.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response("ERR_NOT_FOUND", "The requested resource does not exist", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response("ERR_NOT_FOUND", "The requested resource does not exist", 404)


@app.errorhandler(400)
def handle_bad_request(_err):
    return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {err}", 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
