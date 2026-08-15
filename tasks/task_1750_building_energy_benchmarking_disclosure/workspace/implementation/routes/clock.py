"""Logical clock test-driving endpoint."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import get_context, require_roles
from response import ok
from validation import parse_body, parse_datetime

bp = Blueprint("clock", __name__)


@bp.post("/v1/_clock/set_current_utc")
def set_clock():
    get_context()
    require_roles(["ComplianceOfficer"])
    body = parse_body({"to_iso8601": ("string", True, None)}, allow_empty=False)
    dt = parse_datetime(body["to_iso8601"])
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "to_iso8601 is not a valid ISO 8601 instant")
    db.LOGICAL_CLOCK = dt
    return ok({"current_utc": db.iso_logical(db.LOGICAL_CLOCK)})
