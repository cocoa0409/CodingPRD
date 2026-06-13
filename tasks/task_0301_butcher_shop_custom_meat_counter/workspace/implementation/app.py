"""Butcher Shop & Custom Meat Counter API — Flask entry point.

In-memory storage only; the store starts EMPTY on every boot (no seeding).
start.sh runs this in the foreground, binding 0.0.0.0:$PORT (default 10000).
"""
import os

from flask import Flask

import db
import errors
import response
from routes import register_routes

app = Flask(__name__)
app.url_map.strict_slashes = False

# Store starts empty on every process boot.
db.reset()

register_routes(app)


@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return response.error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    # Unknown route / no resource. Use the catalog's not-found shape.
    eid, status = errors.ERR_NOT_FOUND
    return response.error_response(eid, "Resource not found.", status)


@app.errorhandler(405)
def handle_405(_exc):
    eid, status = errors.ERR_NOT_FOUND
    return response.error_response(eid, "Method not allowed.", status)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, errors.ApiError):
        return response.error_response(exc.error_id, exc.message, exc.http_status)
    # Surface unexpected failures as a generic 400 invalid-request envelope so
    # responses always conform to the standard error structure.
    eid, status = errors.ERR_INVALID_REQUEST
    return response.error_response(eid, "Unexpected error: %s" % exc, status)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
