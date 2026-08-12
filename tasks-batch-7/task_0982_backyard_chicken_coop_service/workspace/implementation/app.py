"""Backyard Chicken Coop Service API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). Storage is in-memory only; a fresh process
starts with an empty store and the logical clock at 2026-05-01T00:00:00Z.
"""
import os

from flask import Flask

from db import store
from errors import ApiError
from response import error_body

app = Flask(__name__)


# Serialize mutations so per-test concurrency never corrupts the store.
@app.before_request
def _acquire_lock():
    store.lock.acquire()


@app.teardown_request
def _release_lock(exc):
    store.lock.release()


@app.errorhandler(ApiError)
def _api_error(err):
    return error_body(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def _not_found(_err):
    return error_body("ERR_INVALID_REQUEST", 404, "Resource or route not found")


@app.errorhandler(405)
def _method_not_allowed(_err):
    return error_body("ERR_INVALID_REQUEST", 405, "Method not allowed")


@app.errorhandler(Exception)
def _internal_error(err):
    return error_body("ERR_INVALID_REQUEST", 500, f"Internal error: {err}")


from routes import clock_routes, config, coops, engagements, households, invoices, orders, routes_stops, subscriptions, visits

for module in (clock_routes, households, config, subscriptions, coops, visits,
               engagements, routes_stops, orders, invoices):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
