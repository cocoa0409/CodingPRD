"""Logical clock test-driving endpoint (not under /district)."""
from flask import Blueprint

import db
from response import ok
from middleware import get_context, require_roles
from validation import parse_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = get_context()
    require_roles(["DistrictAdmin"])
    body = parse_body({"to_iso8601": ("datetime", True, None, None)}, allow_empty=False)
    db.LOGICAL_CLOCK = body["_to_iso8601_dt"]
    return ok({"current_utc": db.iso_out(db.LOGICAL_CLOCK)})
