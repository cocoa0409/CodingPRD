"""Hazmat Transportation Compliance API — Flask entry point.

Mounts all route blueprints under /hazmat and installs envelope-shaped error
handlers. The store (db.store) starts empty on every boot; nothing is seeded.
"""

import os
import traceback

from flask import Flask

import envelope
import errors as errmod
from routes import (
    carriers,
    catalog,
    clock_routes,
    drivers,
    incidents,
    invoices,
    loads,
    papers,
    plans,
    routes_routes,
    shipments,
    vehicles,
)

app = Flask(__name__)

for bp in (
    clock_routes.bp,
    carriers.bp,
    invoices.bp,
    plans.bp,
    catalog.bp,
    drivers.bp,
    vehicles.bp,
    shipments.bp,
    papers.bp,
    loads.bp,
    routes_routes.bp,
    incidents.bp,
):
    app.register_blueprint(bp)


@app.errorhandler(errmod.ApiError)
def handle_api_error(e):
    return envelope.err(e.error_id, e.message, e.status)


@app.errorhandler(404)
def handle_not_found(e):
    return envelope.err("ERR_NOT_FOUND", "The requested path does not exist", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return envelope.err("ERR_NOT_FOUND", "Method not allowed on this path", 405)


@app.errorhandler(Exception)
def handle_unexpected(e):
    traceback.print_exc()
    return envelope.err("ERR_INTERNAL", "Unexpected server error", 500)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
