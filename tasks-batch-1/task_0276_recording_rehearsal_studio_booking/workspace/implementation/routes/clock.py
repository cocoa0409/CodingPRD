"""Test-driving logical clock & hold-release sweep (PRD §2.11, §3.7)."""
from flask import Blueprint

from db import db, clock_now, db_iso
from errors import err
from middleware import get_principal, require_roles
from helpers import get_json_body, require_str
from response import success_object
from serialize import public
from timeutil import parse_iso
from services import booking_logic as bl

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    body = get_json_body()
    to_iso = require_str(body, "to_iso8601")
    dt = parse_iso(to_iso, error_id="ERR_INVALID_REQUEST")
    db.clock["current_utc"] = db_iso(dt)
    return success_object(public(db.clock))


@bp.route("/_sweep/release_expired_holds", methods=["POST"])
def sweep_holds():
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    now = clock_now()
    released_ids = []
    for booking in list(db.bookings.values()):
        if booking["schedule_status"] != "HELD":
            continue
        hold_expires = booking.get("hold_expires_at")
        if hold_expires is None:
            continue
        if parse_iso(hold_expires) < now:
            studio = db.studios[booking["studio_id"]]
            bl.perform_cancellation(booking, studio, booking["client_id"])
            released_ids.append(booking["id"])
    data = {
        "released_count": len(released_ids),
        "released_booking_ids": released_ids,
    }
    return success_object(data)
