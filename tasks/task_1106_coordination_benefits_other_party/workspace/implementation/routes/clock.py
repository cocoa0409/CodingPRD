"""Logical clock test-driving endpoint."""

from flask import Blueprint

from db import stores, clock, parse_iso, parse_iso as _parse
from errors import raise_err, ERR_INVALID_REQUEST
from helpers import body, touch
from middleware import require_roles
from response import success

bp = Blueprint("clock", __name__)


@bp.route("/cob/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    data = body()
    to = data.get("to_iso8601")
    if not to or not isinstance(to, str):
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        dt = parse_iso(to)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp")
    clock.set(dt)
    # Eager side effect: SENT surveys past due -> EXPIRED
    for s in stores["surveys"].values():
        if s.get("status") == "SENT" and s.get("due_at"):
            if _parse(s["due_at"]) < dt:
                s["status"] = "EXPIRED"
                touch(s)
    return success({}, status=200)
