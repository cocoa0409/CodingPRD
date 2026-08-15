"""Air Cargo ULD Management API — entry point.

Flask app wiring: blueprint registration under /cargo and the error
handlers that render every failure in the PRD 2.2 error envelope.
"""

import os

from flask import Flask

from envelope import error_response
from errors import ApiError, ERR_NOT_FOUND
from routes import bookings, claims, clock, customs, dg, flights, plans, ulds

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (flights, bookings, plans, ulds, dg, customs, claims, clock):
    app.register_blueprint(module.bp, url_prefix="/cargo")


@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", f"Unexpected server error: {err}", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
