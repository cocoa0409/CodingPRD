"""Employee Resource Group & Inclusion Program API — Flask entry point.

Storage is entirely in-memory (module-level dicts in db.py). Every boot starts
empty; the logical clock starts at 2026-08-01T00:00:00Z. Nothing is seeded.
"""
import os

from flask import Flask, jsonify

from db import LOCK
from errors import ApiError, ERR_NOT_FOUND
from util import err_body

from routes import (
    clock as clock_routes,
    events as events_routes,
    funding as funding_routes,
    groups as groups_routes,
    memberships as memberships_routes,
    mentoring as mentoring_routes,
    programs as programs_routes,
    sponsors as sponsors_routes,
    surveys as surveys_routes,
    terms as terms_routes,
    venues as venues_routes,
)

app = Flask(__name__)

for module in (programs_routes, sponsors_routes, groups_routes, memberships_routes,
               terms_routes, funding_routes, venues_routes, events_routes,
               surveys_routes, mentoring_routes, clock_routes):
    app.register_blueprint(module.bp)


# Serialize request handling through one re-entrant lock so multi-step
# mutations (cascades, waterfall, promotion) are atomic under concurrency.
@app.before_request
def _acquire_lock():
    LOCK.acquire()


@app.teardown_request
def _release_lock(exc=None):
    try:
        LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(err_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(404)
def handle_not_found(exc):
    return jsonify(err_body(ERR_NOT_FOUND, "resource not found")), 404


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return jsonify(err_body(ERR_NOT_FOUND, "method not allowed")), 405


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return jsonify(err_body("ERR_INTERNAL", str(exc))), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
