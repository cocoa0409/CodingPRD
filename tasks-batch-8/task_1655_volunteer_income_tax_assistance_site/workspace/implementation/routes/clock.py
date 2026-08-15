"""Logical clock test-driving endpoint (PRD §2.5). SponsorAdmin only."""
from flask import Blueprint

import db
from middleware import get_context, require_roles
from response import ok
from validation import parse_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    get_context()
    require_roles(["SponsorAdmin"])
    body = parse_body({"to_iso8601": {"kind": "datetime", "required": True}})
    db.LOGICAL_CLOCK = body["to_iso8601"]
    return ok({"current_utc": db.fmt_ts(db.LOGICAL_CLOCK)})
