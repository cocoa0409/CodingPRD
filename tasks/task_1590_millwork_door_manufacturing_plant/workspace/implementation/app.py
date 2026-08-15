"""Millwork Door Plant API — Flask entry point.

Mounts every route module under the /millwork prefix and installs the
envelope-shaped error handlers. The store (db.py) starts empty on every boot;
nothing is seeded or preloaded.
"""

import os

from flask import Flask

import response
from errors import ApiError
from routes import (batches, drawings, labels, openings, orders, programs,
                    projects, punch, resources, rolls, slots, trips)

API_PREFIX = "/millwork"

app = Flask(__name__)
app.url_map.strict_slashes = False

for blueprint in (projects.bp, resources.bp, rolls.bp, orders.bp, openings.bp,
                  drawings.bp, programs.bp, slots.bp, batches.bp, labels.bp,
                  trips.bp, punch.bp):
    app.register_blueprint(blueprint, url_prefix=API_PREFIX)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return response.error(exc.error_id, exc.message, exc.status)


@app.errorhandler(404)
def handle_not_found(_exc):
    return response.error("ERR_INVALID_REQUEST", "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return response.error("ERR_INVALID_REQUEST", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return response.error("ERR_INVALID_REQUEST", "Unexpected error: %s" % exc, 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
