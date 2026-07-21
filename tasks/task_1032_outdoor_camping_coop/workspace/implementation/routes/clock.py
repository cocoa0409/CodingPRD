from flask import Blueprint
from datetime import timedelta

import core
from core import db, ok, get_body, parse_iso, touch, ApiError

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # Auth-exempt (validation priority 1 excludes this endpoint).
    data = get_body()
    to_iso = data.get("to_iso8601")
    if not isinstance(to_iso, str) or not to_iso:
        raise ApiError("ERR_VALIDATION", "'to_iso8601' is required")
    try:
        new_clock = parse_iso(to_iso)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "'to_iso8601' must be a valid ISO-8601 datetime")

    db.clock = new_clock

    # Expire passes whose entry_date + 1 day is strictly earlier than the new clock.
    for ppass in db.permit_passes.values():
        if ppass["status"] != "ISSUED":
            continue
        if parse_iso(ppass["entry_date"]) + timedelta(days=1) < new_clock:
            ppass["status"] = "EXPIRED"
            touch(ppass)

    return ok({}, status=200)
