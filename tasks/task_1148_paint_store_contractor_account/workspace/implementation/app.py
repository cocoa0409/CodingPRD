"""Entry point: Flask app assembly, error handlers, and route registration."""
import os

from flask import Flask, jsonify

import db
from envelope import err_body
from errors import ApiError
from routes import (
    accounts, jobs, catalog, colormatch, orders, deliveries, specs, rebates,
    mistint, clock,
)

app = Flask(__name__, static_folder=None)


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
def handle_api_error(err):
    return jsonify(err_body(err.error_id, err.message)), err.http_status


@app.errorhandler(404)
def handle_not_found(err):
    return jsonify(err_body("ERR_NOT_FOUND", "resource not found")), 404


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return jsonify(err_body("ERR_NOT_FOUND", "method not allowed")), 405


@app.errorhandler(Exception)
def handle_unexpected(err):
    return jsonify(err_body("ERR_VALIDATION", "unexpected server error: %s" % err)), 500


for module in (accounts, jobs, catalog, colormatch, orders, deliveries, specs,
               rebates, mistint, clock):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
