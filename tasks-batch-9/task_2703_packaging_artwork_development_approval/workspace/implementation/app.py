"""Packaging Artwork Development & Approval API.

Storage is in-memory only and starts completely empty on every boot: no entity is
seeded, preloaded or hardcoded, and every row is created by an API caller.
"""
import os

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

from core import db, parse_dt, request_id, wall_iso
from errors import ApiError
from http_util import auth, body_fields, error_response, ok
from routes.assets import bp as assets_bp
from routes.briefs import bp as briefs_bp
from routes.claims import bp as claims_bp
from routes.element_checks import bp as element_checks_bp
from routes.escapes import bp as escapes_bp
from routes.plates import bp as plates_bp
from routes.printers import bp as printers_bp
from routes.review import bp as review_bp
from routes.runouts import bp as runouts_bp
from routes.versions import bp as versions_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

for blueprint in (
    briefs_bp,
    claims_bp,
    assets_bp,
    versions_bp,
    element_checks_bp,
    review_bp,
    printers_bp,
    plates_bp,
    runouts_bp,
    escapes_bp,
):
    app.register_blueprint(blueprint)


@app.before_request
def _acquire():
    db.lock.acquire()
    g._touched_rows = set()


@app.teardown_request
def _release(exception=None):
    try:
        db.lock.release()
    except RuntimeError:
        pass


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(["PlatformAdmin"])
    body = body_fields(["to_iso8601"])
    parsed = parse_dt(body.get("to_iso8601"))
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 UTC datetime")
    # Setting the clock mutates no entity (PRD 2.4).
    db.clock = parsed
    return ok({})


@app.errorhandler(ApiError)
def _api_error(error):
    return error_response(error)


def _envelope_error(error_id, message, status):
    body = {
        "meta": {"api_request_id": request_id(), "api_request_timestamp": wall_iso()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


@app.errorhandler(404)
def _not_found(error):
    return _envelope_error("ERR_INVALID_REQUEST", "no such route", 404)


@app.errorhandler(405)
def _method_not_allowed(error):
    return _envelope_error("ERR_INVALID_REQUEST", "method not allowed for this route", 405)


@app.errorhandler(Exception)
def _unhandled(error):
    if isinstance(error, ApiError):
        return error_response(error)
    if isinstance(error, HTTPException):
        return _envelope_error("ERR_INVALID_REQUEST", error.description or "request failed",
                               error.code or 400)
    return _envelope_error("ERR_INVALID_REQUEST", "unexpected server error: %s" % error, 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
