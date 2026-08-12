"""Biorepository Consent API — Flask entry point.

In-memory only: all state lives in module-level dicts in db.py and is rebuilt
from nothing on every process boot. No seeding, no persistence.
"""
import os

from flask import Flask

from errors import ApiError, ERRORS
from response import error_response

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

from routes.clock_sweep import bp as clock_sweep_bp
from routes.donors import bp as donors_bp
from routes.kits import bp as kits_bp
from routes.specimens import bp as specimens_bp
from routes.storage import bp as storage_bp
from routes.requests import bp as requests_bp
from routes.agreements import bp as agreements_bp
from routes.keys import bp as keys_bp
from routes.destruction import bp as destruction_bp

for bp in (
    clock_sweep_bp,
    donors_bp,
    kits_bp,
    specimens_bp,
    storage_bp,
    requests_bp,
    agreements_bp,
    keys_bp,
    destruction_bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_404(exc):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(exc):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.http_status, exc.message)
    return error_response("ERR_INVALID_REQUEST", 400, str(exc))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
