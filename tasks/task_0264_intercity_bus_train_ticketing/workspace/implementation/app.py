"""Intercity Ticketing API — Flask entry point.

In-memory only; state lives in db.py module-level dicts and is wiped on every
boot (fresh process). No seeding/preloading of any entity (PRD/skill contract).
"""
import os

from flask import Flask, request

from errors import ApiError
from response import error as error_response
from routes.catalog import bp as catalog_bp
from routes.passengers import bp as passengers_bp
from routes.bookings import bp as bookings_bp
from routes.misc import bp as misc_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(catalog_bp)
app.register_blueprint(passengers_bp)
app.register_blueprint(bookings_bp)
app.register_blueprint(misc_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    # Method not allowed is not in the PRD error catalogue; surface within the
    # standard envelope as a not-found of the requested route+method.
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    # Unexpected server error — keep the envelope shape consistent.
    return error_response("ERR_INVALID_REQUEST", 422, "Unhandled error: %s" % str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
