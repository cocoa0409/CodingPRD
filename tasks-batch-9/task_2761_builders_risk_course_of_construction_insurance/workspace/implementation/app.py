"""Builders Risk / Course of Construction Insurance API.

Entry point: blueprint registration under the /builders-risk prefix, the error
handlers that render the envelope of PRD 2.2, and the WSGI launch.

The in-memory store starts EMPTY on every boot -- nothing is seeded, preloaded or
hardcoded here. Every entity is created by an API caller through a declared endpoint.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes import assignments, claims, clock, coverage_parts, endorsements, facilities, \
    interests, notices, payments, policies, projects

PREFIX = "/builders-risk"

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

for module in (
    projects,
    policies,
    coverage_parts,
    interests,
    endorsements,
    claims,
    payments,
    notices,
    facilities,
    assignments,
    clock,
):
    app.register_blueprint(module.bp, url_prefix=PREFIX)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(404)
def handle_not_found(_exc):
    return jsonify(error_body("ERR_NOT_FOUND", "No such route.")), 404


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return jsonify(
        error_body("ERR_METHOD_NOT_ALLOWED", "This method is not allowed on this route.")
    ), 405


@app.errorhandler(400)
def handle_bad_request(_exc):
    return jsonify(error_body("ERR_INVALID_REQUEST", "Malformed request.")), 400


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    if isinstance(exc, HTTPException):
        status = exc.code or 500
        if status == 404:
            return handle_not_found(exc)
        if status == 405:
            return handle_method_not_allowed(exc)
        return jsonify(error_body("ERR_INVALID_REQUEST", exc.description or "Bad request.")), \
            (status if status < 500 else 500)
    app.logger.exception("unhandled error: %s", exc)
    return jsonify(error_body("ERR_INTERNAL", "Unexpected server error.")), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
