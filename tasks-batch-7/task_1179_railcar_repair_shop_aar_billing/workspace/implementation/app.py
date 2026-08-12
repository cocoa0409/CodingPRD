"""Railcar Repair Shop & AAR Billing API — Flask entry point.

All state is in-memory (db.py); every boot starts empty.
"""
import os

from flask import Flask, jsonify

import db
from errors import ApiError
from common import error_body

import routes_core
import routes_rail
import routes_wo
import routes_billing

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_rail.bp)
app.register_blueprint(routes_wo.bp)
app.register_blueprint(routes_billing.bp)


@app.before_request
def _acquire_lock():
    db.LOCK.acquire()


@app.teardown_request
def _release_lock(exc=None):
    try:
        db.LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def handle_api_error(e):
    resp = jsonify(error_body(e.error_id, e.message))
    resp.status_code = e.status
    return resp


@app.errorhandler(404)
def handle_not_found(e):
    resp = jsonify(error_body("ERR_NOT_FOUND", "Resource not found"))
    resp.status_code = 404
    return resp


@app.errorhandler(405)
def handle_method_not_allowed(e):
    resp = jsonify(error_body("ERR_NOT_FOUND", "Resource not found"))
    resp.status_code = 404
    return resp


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    resp = jsonify(error_body("ERR_INVALID_REQUEST", str(e)))
    resp.status_code = 400
    return resp


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
