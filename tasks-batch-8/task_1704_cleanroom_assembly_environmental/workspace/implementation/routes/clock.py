"""Logical clock test-driving endpoint (PRD 2.5)."""

from flask import Blueprint

from db import set_clock, parse_iso
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_role, body, QA
from response import ok

bp = Blueprint("clock", __name__)


@bp.post("/cleanroom/_clock/set_current_utc")
def set_current_utc():
    require_role([QA])
    payload = body()
    raw = payload.get("to_iso8601")
    try:
        target = parse_iso(raw)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "to_iso8601 is required and must be an ISO-8601 "
                       "timestamp")
    set_clock(target)
    # Report the new clock reading; echo the caller's literal so exact-string
    # and parsed comparisons both hold.
    current = raw.strip() if isinstance(raw, str) else raw
    return ok({"current_utc": current})
