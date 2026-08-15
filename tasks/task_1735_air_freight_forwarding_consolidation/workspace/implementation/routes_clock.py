"""Logical clock test-driving endpoint (PRD §2.9). Mounted WITHOUT the
/air-freight prefix."""
from flask import Blueprint

import services as svc
from db import store
from middleware import get_body, req_datetime, require_roles, ALL_ROLES
from response import ok
from timeutil import iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles(*ALL_ROLES)
def set_current_utc():
    body = get_body()
    to = req_datetime(body, "to_iso8601")
    store.set_clock(to)
    # Eagerly re-evaluate time-driven transitions: booking cutoff auto-close.
    svc.auto_close_bookings()
    return ok({"current_utc": iso(store.now())}, 200)
