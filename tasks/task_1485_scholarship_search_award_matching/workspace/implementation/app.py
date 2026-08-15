"""Scholarship Award Matching API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). In-memory store starts empty on every boot.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import db
from errors import ApiError
from response import error_body

from routes.parties import bp as parties_bp
from routes.programs import bp as programs_bp
from routes.applications import bp as applications_bp
from routes.review import bp as review_bp
from routes.awards import bp as awards_bp
from routes.disbursements import bp as disbursements_bp
from routes.adjustments import bp as adjustments_bp
from routes.renewals import bp as renewals_bp
from routes.stewardship import bp as stewardship_bp
from routes.ops import bp as ops_bp

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


@app.errorhandler(HTTPException)
def handle_http_error(err):
    if err.code == 404:
        return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404
    if err.code == 405:
        return jsonify(error_body("ERR_NOT_FOUND", "Method not allowed")), 404
    return jsonify(error_body("ERR_VALIDATION", err.description or "Bad request")), 400


@app.errorhandler(Exception)
def handle_unexpected(err):
    return jsonify(error_body("ERR_VALIDATION", "Internal error: %s" % err)), 500


for bp in (parties_bp, programs_bp, applications_bp, review_bp, awards_bp,
           disbursements_bp, adjustments_bp, renewals_bp, stewardship_bp, ops_bp):
    app.register_blueprint(bp)


@app.before_request
def _serialize_requests():
    # In-memory store: serialize all requests to keep mutations atomic.
    db.lock().acquire()


@app.teardown_request
def _release_lock(exc=None):
    db.lock().release()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
