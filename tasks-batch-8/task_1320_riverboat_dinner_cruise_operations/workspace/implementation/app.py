"""Riverboat Dinner Cruise API — Flask entry point.

In-memory store only; every process boot yields a pristine empty system.
Reads PORT (default 10000), binds 0.0.0.0, runs in the foreground.
"""
import os

from flask import Flask, jsonify

import response
from errors import ApiError
from routes import (core_entities, cruises, bookings, manifest, galley,
                    staff_assignments, charter, weather, credits, dockops)

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (core_entities, cruises, bookings, manifest, galley,
               staff_assignments, charter, weather, credits, dockops):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    body, status = response.error(exc.error_id, exc.status, exc.message)
    return body, status


@app.errorhandler(404)
def handle_404(exc):
    body, status = response.error("ERR_NOT_FOUND", 404, "Resource not found")
    return body, status


@app.errorhandler(405)
def handle_405(exc):
    body, status = response.error("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed")
    return body, status


@app.errorhandler(500)
def handle_500(exc):
    body, status = response.error("ERR_INTERNAL", 500, "Internal server error")
    return body, status


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
