"""Logical clock test-driving endpoint."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import get_context, require_roles
from response import ok
from validation import validate_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = get_context()
    require_roles(["BranchManager"])
    body = validate_body({"to_iso8601": ("string", True)})
    raw = body["to_iso8601"]
    if not db.is_valid_datetime_string(raw):
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 is not a valid ISO 8601 instant")
    db.LOGICAL_CLOCK = db.parse_datetime(raw)
    return ok({"current_utc": db.iso_logical(db.LOGICAL_CLOCK)})
