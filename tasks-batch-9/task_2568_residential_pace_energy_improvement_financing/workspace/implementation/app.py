"""Residential PACE Energy-Improvement Financing API.

Flask entry point. Storage is in-memory only and starts empty on every boot:
the harness relaunches this process before every test, and no fixture, seed or
cached file is ever read.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import db
import response
import routes_agreement
import routes_application
import routes_assessment
import routes_funding
import routes_reference
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_reference.bp)
app.register_blueprint(routes_application.bp)
app.register_blueprint(routes_agreement.bp)
app.register_blueprint(routes_funding.bp)
app.register_blueprint(routes_assessment.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return response.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code == 404:
        return response.error("ERR_NOT_FOUND", "Unknown route", 404)
    if exc.code == 405:
        return response.error("ERR_NOT_FOUND", "Method not allowed", 405)
    if exc.code == 400:
        return response.error("ERR_VALIDATION", "Malformed request", 400)
    return response.error(
        "ERR_VALIDATION", exc.description or "Request could not be processed", exc.code
    )


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return response.error("ERR_VALIDATION", "Unexpected server error: %s" % exc, 500)


@app.get("/health")
def health():
    return jsonify({"status": "ok", "current_utc": db.now_iso()}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
