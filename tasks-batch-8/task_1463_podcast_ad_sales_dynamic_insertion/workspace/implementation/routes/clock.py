"""Logical clock test-driver endpoint."""

from flask import Blueprint, request

import db
from errors import err_invalid
from helpers import body_of, parse_dt
from middleware import require_roles
from response import success_object
from services import Changes, recompute_all_shows, recompute_all_slots

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles({"AdOps"})
    body = body_of(request)
    raw = body.get("to_iso8601")
    if raw is None or parse_dt(raw) is None:
        raise err_invalid("Field 'to_iso8601' must be an ISO 8601 UTC timestamp")
    db.set_clock(raw.strip())
    # Clock set is a system-wide event: recompute every show's forecast and
    # every episode's slot occupancy against the new time.
    ch = Changes()
    recompute_all_shows(ch)
    recompute_all_slots(ch)
    ch.commit()
    return success_object({"current_utc": db.clock_raw})
