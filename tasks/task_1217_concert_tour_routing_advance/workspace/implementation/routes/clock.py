"""Logical-clock endpoint (PRD 2.5). TourManager-only. Setting the clock
triggers the hold-expiry sweep, the automatic ON_SALE -> IN_PROGRESS
crossing, and rest-day rechecks on locked legs."""
from flask import Blueprint

from db import clock
from middleware import authenticate, ROLE_TOUR_MANAGER, get_body, v_dt, fmt_dt
from response import success_object
from services import sweep_clock

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(frozenset({ROLE_TOUR_MANAGER}))
    b = get_body()
    to = v_dt(b, "to_iso8601")
    clock["now"] = to
    sweep_clock()
    return success_object({"current_utc": fmt_dt(clock["now"])})
