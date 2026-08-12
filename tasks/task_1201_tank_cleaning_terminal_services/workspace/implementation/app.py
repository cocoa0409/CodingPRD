"""Tank Cleaning & Terminal Services API — entry point.

All state is in-memory (module-level dicts); nothing is seeded at startup and
nothing is persisted. The harness restarts the process before every test.
"""

import os

from flask import Flask

from core import ApiError, error_response, ERR_NOT_FOUND, ERR_INVALID_REQUEST
import routes_registry
import routes_jobs
import routes_waste
import routes_entry
import routes_inspect
import routes_wastewater

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (routes_registry, routes_jobs, routes_waste, routes_entry,
               routes_inspect, routes_wastewater):
    app.register_blueprint(module.bp, url_prefix="/ops")


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    return error_response(ApiError(ERR_INVALID_REQUEST, 400, str(e)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            use_reloader=False)
