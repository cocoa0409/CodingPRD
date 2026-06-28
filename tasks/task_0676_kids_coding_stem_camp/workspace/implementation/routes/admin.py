"""Test-driving / admin sweeps: logical clock and billing cycle (PRD §2.5, §3.3)."""
from flask import Blueprint

from clock import clock
from db import db
from response import success
from middleware import get_auth, require_role
from validators import get_body, parse_iso, invalid
from services.pricing import membership_cycle_credit

bp = Blueprint("admin", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    body = get_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str) or raw == "":
        raise invalid("to_iso8601 is required and must be an ISO 8601 string.")
    dt = parse_iso(raw, "to_iso8601")
    clock.set(dt)
    return success({})


@bp.route("/_billing/advance-cycle", methods=["POST"])
def advance_cycle():
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    body = get_body()
    member_id = body.get("member_id")
    for m in db.memberships.values():
        if member_id is not None and m["member_id"] != member_id:
            continue
        if m["status"] != "ACTIVE":
            continue  # PAUSED/CANCELLED skipped entirely
        credit = membership_cycle_credit(m)
        if credit:
            member = db.members.get(m["member_id"])
            guardian = db.guardians.get(member["guardian_id"]) if member else None
            if guardian is not None:
                guardian["wallet_credit_cents"] += credit
                db.touch(guardian)
        m["sessions_used_this_cycle"] = 0
        m["cycle_index"] += 1
        db.touch(m)
    return success({})
