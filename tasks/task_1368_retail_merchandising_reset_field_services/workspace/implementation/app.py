"""Retail Merchandising Reset Field Services API — entry point.

Mounts all resource blueprints under /retail-reset plus the logical-clock
test-driving endpoint at /_clock/set_current_utc. Storage is in-memory only;
the store starts empty on every boot.
"""
import os
import sys

from flask import Flask

import errors
import response as resp
from routes import (assignments, clients, clock, exceptions, invoices, mileage,
                    project_stores, projects, reps, rework, shipments, stores,
                    store_visits)

API_PREFIX = "/retail-reset"

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (clients, stores, reps, projects, project_stores, assignments,
               store_visits, exceptions, rework, shipments, mileage, invoices):
    app.register_blueprint(module.bp, url_prefix=API_PREFIX)
app.register_blueprint(clock.bp, url_prefix="/_clock")


@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return resp.error_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_not_found(_exc):
    return resp.error_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return resp.error_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, errors.ApiError):
        return resp.error_response(exc.error_id, exc.http_status, exc.message)
    return resp.error_response("ERR_INTERNAL", 500, str(exc)), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
