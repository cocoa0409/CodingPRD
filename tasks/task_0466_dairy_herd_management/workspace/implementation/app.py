"""Dairy Herd Management API — Flask entry point.

In-memory storage only; the store starts EMPTY on every boot. No seeding.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.core import bp as core_bp
from routes.animals import bp as animals_bp
from routes.shifts import bp as shifts_bp
from routes.breeding import bp as breeding_bp
from routes.health import bp as health_bp
from routes.milkchecks import bp as milkchecks_bp
from routes.culls import bp as culls_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(core_bp)
app.register_blueprint(animals_bp)
app.register_blueprint(shifts_bp)
app.register_blueprint(breeding_bp)
app.register_blueprint(health_bp)
app.register_blueprint(milkchecks_bp)
app.register_blueprint(culls_bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    # Unknown route — return the standard error envelope.
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(_exc):
    return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(400)
def handle_400(_exc):
    return error_response("ERR_INVALID_REQUEST", "Malformed request", 422)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    return error_response("ERR_INTERNAL", "Internal server error: %s" % exc, 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
