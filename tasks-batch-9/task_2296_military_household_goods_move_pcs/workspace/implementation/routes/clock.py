"""Logical-clock test hook (SCAFFOLD §1.5 test-driving endpoint)."""

from flask import Blueprint, g, request

from db import set_clock
from errors import ApiError
from middleware import ALL_ROLES, USER_ROLE_HEADER
from response import fmt_dt, ok
from validation import get_body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    role = request.headers.get(USER_ROLE_HEADER)
    if role is not None and role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    g.user_id = request.headers.get("X-User-ID")
    g.role = role
    g.touched = set()
    body = get_body()
    current_utc = req_dt(body, "current_utc")
    set_clock(current_utc)
    return ok({"current_utc": fmt_dt(current_utc)})
