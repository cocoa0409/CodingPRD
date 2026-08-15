"""Clock control and the operations sweep (PRD §2.4, §2.10)."""

from datetime import timedelta

from flask import Blueprint

from db import db, _parse_iso
from errors import ApiError
from middleware import require_roles, get_body, validate_payload
from response import success
from services.core import release_reserved_bike, touch, NO_SHOW_LIMIT

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {"to_iso8601": {"type": "string", "required": True}})
    try:
        db.clock = _parse_iso(body["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "to_iso8601 must be an ISO-8601 instant")
    return success({"current_utc": db.now_iso()})


@bp.post("/ops/run-sweep")
def run_sweep():
    require_roles("ShopCoordinator")
    now = db.now()
    today = db.today()

    participants_expired = 0
    shifts_marked = 0
    sessions_marked = 0
    memberships_expired = 0

    # 1. Expire participants past their enrollment deadline (release reserved bikes).
    for p in list(db.participants.values()):
        if p["status"] in ("ENROLLED", "HOURS_MET") and now > _parse_iso(p["enrollment_deadline"]):
            release_reserved_bike(p)
            p["status"] = "EXPIRED"
            touch(p)
            participants_expired += 1

    # 2. Past-due SCHEDULED shifts -> NO_SHOW (clock >= scheduled_end + 30m), feeding
    #    the no-show strike cascade. Process in scheduled_start ASC, ties by created_at ASC.
    due_shifts = [
        s for s in db.shifts.values()
        if s["status"] == "SCHEDULED" and now >= _parse_iso(s["scheduled_end"]) + timedelta(minutes=30)
    ]
    due_shifts.sort(key=lambda s: (s["scheduled_start"], s["created_at"]))
    for s in due_shifts:
        s["status"] = "NO_SHOW"
        touch(s)
        shifts_marked += 1
        vol = db.volunteers.get(s["volunteer_id"])
        if vol is not None:
            vol["no_show_count"] += 1
            if vol["no_show_count"] >= NO_SHOW_LIMIT and vol["engagement_status"] == "ACTIVE":
                # Strike three: suspend + cancel every remaining SCHEDULED shift.
                vol["engagement_status"] = "SUSPENDED"
                for other in db.shifts.values():
                    if other["volunteer_id"] == vol["id"] and other["status"] == "SCHEDULED":
                        other["status"] = "CANCELLED"
                        touch(other)
            touch(vol)

    # 3. Past-due BOOKED sessions -> NO_SHOW (clock >= start_time + 30m).
    for s in list(db.tool_sessions.values()):
        if s["status"] == "BOOKED" and now >= _parse_iso(s["start_time"]) + timedelta(minutes=30):
            s["status"] = "NO_SHOW"
            touch(s)
            sessions_marked += 1

    # 4. Expire memberships whose end_date has passed (clock date > end_date).
    for m in list(db.memberships.values()):
        if m["status"] in ("ACTIVE", "SUSPENDED"):
            try:
                end = _parse_iso(m["end_date"]).date()
            except (ValueError, TypeError):
                continue
            if today > end:
                m["status"] = "EXPIRED"
                touch(m)
                memberships_expired += 1

    return success({
        "participants_expired": participants_expired,
        "shifts_marked_no_show": shifts_marked,
        "sessions_marked_no_show": sessions_marked,
        "memberships_expired": memberships_expired,
    })
