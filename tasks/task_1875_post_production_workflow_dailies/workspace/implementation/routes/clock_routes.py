"""Logical clock test-driving endpoint (PRD §2.4)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_REQUEST
from helpers import get_json_body, require_fields, check_datetime_string, touch
from middleware import require_roles
from response import success_object
from clock import clock as logical_clock, format_iso, _parse_iso

bp = Blueprint("clock_routes", __name__)


def _no_show_sweep():
    """Any booking still RESERVED whose session_date has arrived and whose
    end_hour has passed without a check-in transitions to NO_SHOW."""
    now = logical_clock.now()
    today = now.date().isoformat()
    for booking in db.bookings.values():
        if booking["status"] != "RESERVED":
            continue
        session_date = booking["session_date"]
        if session_date < today:
            booking["status"] = "NO_SHOW"
            touch(booking)
        elif session_date == today and now.hour >= booking["end_hour"]:
            booking["status"] = "NO_SHOW"
            touch(booking)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles(("FacilityAdmin",))
    body = get_json_body()
    require_fields(body, ("to_iso8601",))
    to_iso8601 = check_datetime_string(body, "to_iso8601")
    new_now = logical_clock.set(to_iso8601)
    # Advancing the clock is not inert: it triggers the no-show sweep and any
    # other time-dependent automatic transitions.
    _no_show_sweep()
    return success_object({"current_utc": format_iso(new_now)})
