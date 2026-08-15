"""Logical clock test-driving endpoint."""
from flask import Blueprint, request

import db
from middleware import auth, require_role
from response import success_object
from validation import F, validate_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    user_id, role = auth()
    body = validate_body([F("to_iso8601", "datetime")])
    require_role(role, {"ProgramAdmin"})
    db.store.clock = body["to_iso8601"]
    # Echo the caller-supplied string verbatim as current_utc
    raw = None
    try:
        raw = request.get_json(silent=True).get("to_iso8601")
    except Exception:
        raw = None
    db.store.clock_raw = raw if isinstance(raw, str) else None
    from timeutil import fmt
    return success_object({
        "current_utc": db.store.clock_raw if db.store.clock_raw else fmt(db.store.clock)
    })
