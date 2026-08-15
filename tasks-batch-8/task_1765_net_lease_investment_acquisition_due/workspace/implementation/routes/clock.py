"""Logical clock administration (PRD §2.6)."""

from flask import Blueprint

import db
from middleware import require_role
from response import ok
from routes.common import body, req_dt
from services import domain

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_role("PlatformAdmin")
    data = body()
    to_iso8601 = req_dt(data, "to_iso8601")
    db.set_clock(db.parse_dt(to_iso8601))
    # Advancing the clock fires time-based system transitions atomically.
    domain.fire_time_transitions()
    return ok({"current_utc": db.render_dt(db.clock_now())}, 200)
