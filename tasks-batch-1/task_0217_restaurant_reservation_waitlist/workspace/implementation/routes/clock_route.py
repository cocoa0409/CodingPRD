"""Test-only clock endpoint (PRD §3.9).

Pins the server's notion of current UTC. Per PRD §2.1 this endpoint is
explicitly outside the authenticated set (no auth headers required), even
though the scaffold attributes it conceptually to the Manager. Advancing the
clock may fire system transitions (waitlist EXPIRED, hold EXPIRED), which are
applied by the request-level sweep.
"""
from flask import Blueprint

import clock
from response import object_response
from timeutil import parse_iso, format_iso
from validators import get_body, require_str
from services.system_expiry import sweep_all

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    # No authentication: PRD §2.1 places this endpoint outside the
    # authenticated set.
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    dt = parse_iso(to_iso, "to_iso8601")
    clock.set_now(dt)
    # advancing the clock may make system transitions due
    sweep_all()
    return object_response({"current_utc": format_iso(clock.now())}, 200)
