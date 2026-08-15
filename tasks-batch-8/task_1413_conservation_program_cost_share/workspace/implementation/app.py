"""EQIP Cost-Share API — Flask entry point.

In-memory only: all state lives in db.STORE dicts; nothing is seeded at boot;
the logical clock starts at 2026-08-01T00:00:00Z on every fresh process.
"""
import os

from flask import Flask

from db import LOCK
from errors import ApiError
from response import err
from routes import (
    advances, applicants, applications, clock, contracts, demands,
    modifications, obligations, payment_requests, practice_items, programs,
    spot_checks,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (
    programs.bp,
    applicants.bp,
    applications.bp,
    contracts.bp,
    practice_items.bp,
    payment_requests.bp,
    advances.bp,
    modifications.bp,
    spot_checks.bp,
    obligations.bp,
    demands.bp,
    clock.bp,
):
    app.register_blueprint(bp)


@app.before_request
def _acquire_lock():
    # Serialize request handling: the dev server is threaded, and pool-ledger /
    # sweep mutations must be atomic with respect to one another.
    LOCK.acquire()


@app.teardown_request
def _release_lock(exc=None):
    LOCK.release()


@app.errorhandler(ApiError)
def _api_error(e):
    return err(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _not_found(e):
    return err("ERR_INVALID_REQUEST", 404, "Route not found")


@app.errorhandler(405)
def _method_not_allowed(e):
    return err("ERR_INVALID_REQUEST", 405, "Method not allowed")


@app.errorhandler(Exception)
def _unhandled(e):
    return err("ERR_INVALID_REQUEST", 500, f"Internal error: {type(e).__name__}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
