"""Defensible Space & Fuels Inspection API — application entry point.

Storage is in-memory only and starts completely empty on every boot; the
harness relaunches this process before every test.
"""

import os
import traceback

from flask import Flask, g, jsonify

from errors import ApiError
from response import error_body
from routes import (
    abatement, certificates, clock, communities, cycles, findings, inspections, notices,
    parcels, people, support,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (
    cycles, communities, parcels, people, inspections, findings, notices, abatement,
    support, certificates, clock,
):
    app.register_blueprint(module.bp)


@app.before_request
def _prepare_request():
    # Per-request revision bookkeeping: a cascade advances each entity's
    # version by exactly 1 however many links touch it (PRD section 2.10).
    g.touched = set()


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(404)
def _handle_not_found(exc):
    return jsonify(error_body("ERR_INVALID_REQUEST", "No such route.")), 404


@app.errorhandler(405)
def _handle_method_not_allowed(exc):
    return jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed.")), 405


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return _handle_api_error(exc)
    traceback.print_exc()
    return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
    )
