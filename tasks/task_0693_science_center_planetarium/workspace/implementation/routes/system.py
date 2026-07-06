"""System endpoints: health probe, logical clock, deferred sweeps."""
from flask import Blueprint

from db import db, touch
from clock import parse_iso
from errors import err, ERR_INVALID_REQUEST
from middleware import authenticate, require_role
from response import success
from services.common import get_body
from services.show_logic import recompute_seats_sold, bubble_after_recompute

bp = Blueprint("system", __name__)


@bp.route("/_health", methods=["GET"])
def health():
    # Unauthenticated health probe (PRD §2.1).
    return success({}, status=200)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"FacilityAdmin"})
    body = get_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: to_iso8601")
    dt = parse_iso(body["to_iso8601"])
    if dt is None:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO8601 instant")
    with db.lock:
        db.clock.set(dt)
    return success({}, status=200)


@bp.route("/_sweeps/run", methods=["POST"])
def run_sweeps():
    _, role = authenticate()
    require_role(role, {"FacilityAdmin"})
    with db.lock:
        now = db.clock.now
        # 1) Membership expiry: ACTIVE cards whose expires_at the clock reached.
        for m in db.memberships.values():
            if m["status"] == "ACTIVE" and m.get("_expires_at_dt") is not None:
                if now >= m["_expires_at_dt"]:
                    m["status"] = "EXPIRED"
                    touch(m)
        # 2) Hold-expiry: HELD ShowBookings past their 30-minute window are
        #    released to CANCELLED; seats returned; SOLD_OUT -> OPEN bubble-up.
        affected_shows = set()
        for b in db.show_bookings.values():
            if b["status"] == "HELD":
                expiry = db.clock.plus_minutes(b["_held_at_dt"], 30)
                if now >= expiry:
                    b["status"] = "CANCELLED"
                    touch(b)
                    affected_shows.add(b["show_event_id"])
        for sid in affected_shows:
            show = db.shows.get(sid)
            if show is None:
                continue
            recompute_seats_sold(show)
            bubble_after_recompute(show)
            touch(show)
    return success({}, status=200)
