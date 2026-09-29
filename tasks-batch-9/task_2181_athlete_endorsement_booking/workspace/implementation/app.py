"""Athlete Endorsement & Appearance Booking API.

Entry point: registers the route blueprints, installs the envelope-shaped
error handlers and serves on 0.0.0.0:$PORT. All state lives in process memory
and starts empty on every boot -- nothing is seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from store import LOCK

from routes.bookings import bp as bookings_bp
from routes.core import bp as core_bp
from routes.deliverables import bp as deliverables_bp
from routes.disclosures import bp as disclosures_bp
from routes.engagements import bp as engagements_bp
from routes.negotiation import bp as negotiation_bp
from routes.settlement import bp as settlement_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

for blueprint in (core_bp, negotiation_bp, engagements_bp, bookings_bp,
                  deliverables_bp, disclosures_bp, settlement_bp):
    app.register_blueprint(blueprint)


@app.before_request
def _serialise_requests():
    LOCK.acquire()


@app.teardown_request
def _release_requests(exc=None):
    try:
        LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(exc):
    status = exc.code or 500
    if status == 404:
        return error_response("ERR_INVALID_REQUEST", "resource path not found", 404)
    if status == 405:
        return error_response("ERR_INVALID_REQUEST", "method not allowed", 405)
    if status == 400:
        return error_response("ERR_INVALID_REQUEST", "malformed request", 400)
    return error_response("ERR_INVALID_REQUEST", exc.description or "request failed", status)


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    return error_response("ERR_INVALID_REQUEST", "unexpected server error: %s" % exc, 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
