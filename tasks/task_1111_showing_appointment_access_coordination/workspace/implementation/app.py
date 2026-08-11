"""Showing Access Coordination API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). In-memory storage only; the store starts
empty on every boot — nothing is seeded at startup.
"""

import os

from flask import Flask

import errors as errmod
import response
from routes import agents, credentials_feedback, listings, ops, sellers, showing_requests

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(sellers.bp)
app.register_blueprint(agents.bp)
app.register_blueprint(listings.bp)
app.register_blueprint(showing_requests.bp)
app.register_blueprint(credentials_feedback.bp)
app.register_blueprint(ops.bp)


@app.errorhandler(errmod.ApiError)
def handle_api_error(e):
    return response.error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return response.error(errmod.ERR_INVALID_REQUEST, "Route not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return response.error(errmod.ERR_INVALID_REQUEST, "Method not allowed.", 405)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errmod.ApiError):
        return response.error(e.error_id, e.message, e.http_status)
    return response.error(errmod.ERR_INVALID_REQUEST,
                          f"Unexpected error: {e}", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
