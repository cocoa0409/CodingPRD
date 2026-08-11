"""Logical clock test-driving endpoint (exempt from auth header presence)."""
from flask import Blueprint, request

import errors
import services
from db import db
from middleware import body_json
from response import ok_object

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    # Exempt from validation priority 1 (header presence). If a role header
    # is supplied anyway, the capability remains OpsAdmin-only.
    role = request.headers.get("X-User-Role")
    if role is not None and role != "OpsAdmin":
        raise errors.unauthorized()
    d = body_json()
    to = d.get("to_iso8601")
    if to is None:
        raise errors.invalid_request("required field missing: to_iso8601")
    if not isinstance(to, str):
        raise errors.invalid_request("field to_iso8601 must be a string")
    try:
        dt = services.parse_datetime(to)
    except (ValueError, TypeError):
        raise errors.invalid_request("to_iso8601 is not a valid ISO8601 timestamp")
    with db.lock:
        db.clock = dt
        services.run_time_transitions()
    return ok_object({"now_iso8601": services.fmt_dt(db.clock)})
