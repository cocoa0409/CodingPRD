"""School Facility Rental API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). Storage is in-memory only and starts
empty on every boot; the logical clock starts at exactly 2026-08-01T00:00:00Z
and never falls back to wall-clock time.
"""
import os

from flask import Flask

import errors
import response
from routes import core, ops

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(core.bp)
app.register_blueprint(ops.bp)


@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return response.error(err)


@app.errorhandler(404)
def handle_404(err):
    return response.error(errors.not_found("Resource does not exist"))


@app.errorhandler(405)
def handle_405(err):
    return response.error(errors.not_found("Resource does not exist"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, errors.ApiError):
        return response.error(err)
    return response.error(errors.ApiError("ERR_INTERNAL", 500, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
