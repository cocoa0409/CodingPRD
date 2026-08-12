"""Logical clock endpoint (test-driving, PRD §2.4)."""
from flask import Blueprint, request

import db
from middleware import auth_context, require_role
from response import success
from util import bad_request, body_json, need, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth_context()
    require_role(request.headers.get("X-User-Role"), {"DistrictStaffingAdmin"})
    body = body_json(request)
    to_iso = need(body, "to_iso8601")
    dt = parse_dt(to_iso)
    if dt is None:
        bad_request("to_iso8601 must be an ISO 8601 timestamp")
    db.set_now(dt)
    return success({}, "object", 200)
