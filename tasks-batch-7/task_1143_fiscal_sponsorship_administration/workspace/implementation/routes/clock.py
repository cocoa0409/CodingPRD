"""Logical clock test-driving endpoint (PRD §2.4)."""

from flask import Blueprint

from db import iso, now, parse_iso_datetime, set_clock
from envelope import ok
from errors import ERR_VALIDATION, raise_err
from security import auth, body, req_str, require_role

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    data = body()
    to_iso8601 = req_str(data, "to_iso8601")
    uid, role = auth()
    require_role(role, {"SponsorAdmin"})
    dt = parse_iso_datetime(to_iso8601)
    if dt is None:
        raise_err(ERR_VALIDATION, "to_iso8601 must be an ISO 8601 UTC datetime")
    set_clock(dt)
    return ok({"current_utc": iso(now())})
