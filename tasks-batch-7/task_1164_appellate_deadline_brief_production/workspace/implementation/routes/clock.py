"""Test-driving clock endpoints (PRD §2.5)."""
from flask import Blueprint

from db import now_iso, set_clock, parse_iso, fmt_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success_object
from services.core import get_body

bp = Blueprint("clock", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")


@bp.post("/appellate/_clock/set_current_utc")
def set_current_utc():
    auth = get_auth()
    require_roles(auth, ("CourtAdmin",))
    body = get_body()
    to = body.get("to_iso8601")
    if not isinstance(to, str):
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO8601 string", 400)
    try:
        dt = parse_iso(to)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO8601 timestamp", 400)
    set_clock(fmt_iso(dt))
    return success_object({"current_utc": now_iso()})


@bp.get("/appellate/_clock/current_utc")
def get_current_utc():
    auth = get_auth()
    require_roles(auth, ALL)
    return success_object({"current_utc": now_iso()})
