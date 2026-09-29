"""Mortgage Loan Originator Licensing & Compensation Compliance API.

Python + Flask, in-memory only. Nothing is seeded at startup: every entity in
this service is created through the declared endpoints.
"""
import os

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

import db as store
from errors import ApiError
from response import error_body
from routes import (ads, audit, ce, comp_records, exams, investigations,
                    licenses, loans, ops, originators, plans, pricing,
                    sponsorships)

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

BLUEPRINTS = (
    originators.bp,
    licenses.bp,
    sponsorships.bp,
    ce.bp,
    plans.bp,
    loans.bp,
    pricing.bp,
    comp_records.bp,
    ads.bp,
    exams.bp,
    investigations.bp,
    audit.bp,
    ops.bp,
)

for blueprint in BLUEPRINTS:
    app.register_blueprint(blueprint)


@app.before_request
def _acquire():
    """One request at a time: every mutation sequence is atomic."""
    store.lock.acquire()
    g._lock_held = True
    g._touched = set()


@app.teardown_request
def _release(exc=None):
    if getattr(g, "_lock_held", False):
        g._lock_held = False
        try:
            store.lock.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _api_error(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(404)
def _not_found(exc):
    return jsonify(error_body(
        "ERR_RESOURCE_NOT_FOUND", "The requested resource does not exist.")), 404


@app.errorhandler(405)
def _method_not_allowed(exc):
    return jsonify(error_body(
        "ERR_INVALID_REQUEST", "That method is not allowed on this path.")), 405


@app.errorhandler(HTTPException)
def _http_exception(exc):
    status = exc.code or 500
    if status == 404:
        return _not_found(exc)
    if status == 405:
        return _method_not_allowed(exc)
    if status < 500:
        return jsonify(error_body(
            "ERR_INVALID_REQUEST", exc.description or "Malformed request.")), status
    return jsonify(error_body("ERR_INTERNAL", "Internal server error.")), status


@app.errorhandler(Exception)
def _unhandled(exc):
    if isinstance(exc, HTTPException):
        return _http_exception(exc)
    return jsonify(error_body("ERR_INTERNAL", "Internal server error.")), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
