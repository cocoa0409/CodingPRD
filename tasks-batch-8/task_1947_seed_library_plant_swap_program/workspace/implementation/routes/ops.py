"""Clock + ops-run endpoints."""

from flask import Blueprint
from db import db, parse_iso, iso_z
from middleware import require_roles
from validate import get_body, req_string
from response import success_object
from errors import invalid_request
from services.core import recompute_member

bp = Blueprint("ops", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    require_roles("ProgramAdmin")
    body = get_body()
    to_iso = req_string(body, "to_iso8601")
    dt = parse_iso(to_iso)
    if dt is None:
        raise invalid_request("to_iso8601 must be an ISO8601 datetime.")
    db.set_clock(dt)
    return success_object({"current_utc": iso_z(db.now())})


@bp.post("/api/ops/run-daily-sweep")
def run_daily_sweep():
    require_roles("ProgramAdmin")
    now = db.now()
    # Pass 1: flip ACTIVE checkouts with due_at < now, ordered due_at ASC, created_at ASC
    actives = [c for c in db.checkouts.values() if c["status"] == "ACTIVE"]
    actives.sort(key=lambda c: (c["_due_at_dt"], c["_seq"]))
    flipped = 0
    touched_members = set()
    for c in actives:
        if c["_due_at_dt"] < now:
            c["status"] = "OVERDUE"
            db.touch(c)
            flipped += 1
            touched_members.add(c["member_id"])
    # Pass 2: suspension sweep over ACTIVE members ordered by created_at ASC
    members = sorted(db.members.values(), key=lambda m: m["_seq"])
    suspended = 0
    for m in members:
        if m["id"] in touched_members:
            recompute_member(m)
        if m["status"] == "ACTIVE" and m["overdue_checkout_count"] >= 3:
            m["status"] = "SUSPENDED"
            db.touch(m)
            suspended += 1
    # make sure counters on touched-but-already-suspended members are right too
    for mid in touched_members:
        recompute_member(db.members[mid])
    return success_object({
        "overdue_flipped_count": flipped,
        "members_suspended_count": suspended,
        "members_reinstated_count": 0,
    })
