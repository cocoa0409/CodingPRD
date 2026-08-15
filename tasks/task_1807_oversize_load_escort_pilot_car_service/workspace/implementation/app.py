"""Oversize Load Escort API — entry point.

In-memory store, logical clock, Flask. Boots clean from a fresh process;
no entity seeding at startup (the store starts empty).
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes import clock, carriers, escorts, jobs, legs, permits, surveys, assignments, delays, incidents, invoices

for module in (clock, carriers, escorts, jobs, legs, permits, surveys, assignments,
               delays, incidents, invoices):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_not_found(_exc):
    return error_response("ERR_INVALID_REQUEST", 404, "Route not found")


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    app.logger.exception("Unexpected error: %s", exc)
    return error_response("ERR_INVALID_REQUEST", 500, "Internal server error")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
