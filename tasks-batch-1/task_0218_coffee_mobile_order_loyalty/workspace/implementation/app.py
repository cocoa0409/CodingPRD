"""Coffee Mobile Order & Loyalty API — entry point.

In-memory only; no seeding at startup. State is wiped on every fresh process boot
because all collections live in module-level dicts that start empty.
"""
import os
import logging

from flask import Flask
from werkzeug.exceptions import HTTPException

# Silence werkzeug per-request access logging. Under the 8x-concurrent per-test
# reboot sweep, each request's stderr log line adds I/O contention that can slow
# boot/readiness; quieting it keeps restarts inside the runner's health window.
logging.getLogger("werkzeug").setLevel(logging.ERROR)

from errors import ApiError
from response import error_response
from routes.members import bp as members_bp
from routes.rewards import bp as rewards_bp
from routes.catalog import bp as catalog_bp
from routes.orders import bp as orders_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(members_bp)
app.register_blueprint(rewards_bp)
app.register_blueprint(catalog_bp)
app.register_blueprint(orders_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    # Unmatched route -> ERR_NOT_FOUND envelope.
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    if isinstance(e, HTTPException):
        # Map remaining werkzeug HTTP errors through the envelope.
        code = e.code or 500
        if code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        if code == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)
        return error_response("ERR_INVALID_REQUEST", str(e), code)
    # Unexpected server error
    return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % str(e), 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
