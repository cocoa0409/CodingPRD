"""Test-driving logical clock (PRD §2.6)."""
from flask import Blueprint

import errors
from db import store, LOCK, parse_iso, iso_millis
from middleware import get_identity, require_role, get_json_body
from response import object_response

bp = Blueprint("clock", __name__)


@bp.route("/bridal-beauty/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = get_identity()
    require_role(role, {"Coordinator"})
    body = get_json_body()
    if "to_iso8601" not in body:
        raise errors.invalid_request("to_iso8601 is required")
    dt = parse_iso(body["to_iso8601"])
    if dt is None:
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 datetime")
    with LOCK:
        store.clock_now = dt
        return object_response({"current_utc": iso_millis(dt)}, 200)
