"""IV Hydration & Vitamin Drip Bar API — Flask entry point.

In-memory only. The store starts empty on every boot; nothing is seeded.
Re-invoking start.sh (per-test-server isolation) restarts the process and
wipes all state.
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response
from routes.appointments import bp as appointments_bp
from routes.catalog import bp as catalog_bp
from routes.clinical import bp as clinical_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(catalog_bp)
app.register_blueprint(appointments_bp)
app.register_blueprint(clinical_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    # Unknown route / path -> standard not-found envelope.
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 422)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
