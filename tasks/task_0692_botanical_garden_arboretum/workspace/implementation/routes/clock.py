"""Logical clock control + time-driven sweeps (PRD §2.4, §2.5)."""
from datetime import datetime, timezone

from flask import Blueprint

import errors
from db import db, iso, now
from middleware import get_identity, require_role
from response import success
from services.common import get_body, touch
from services import cascade

bp = Blueprint("clock", __name__)


def _parse_iso(value):
    if not isinstance(value, str):
        raise errors.validation("to_iso8601 must be an ISO 8601 string")
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise errors.validation("to_iso8601 is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_identity()
    require_role(role, {"GardenAdmin"})

    body = get_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise errors.validation("Missing required field: to_iso8601")
    target = _parse_iso(body["to_iso8601"])

    db.now = target
    current = now()

    expired_reservation_ids = []
    lapsed_membership_ids = []

    # Sweep 1: expire stale HELD reservations whose slot has ended.
    for res in list(db.reservations.values()):
        if res["status"] != "HELD":
            continue
        slot = db.time_slots.get(res["time_slot_id"])
        if slot is None:
            continue
        if current >= slot["ends_at"]:
            res["status"] = "EXPIRED"
            touch(res)
            cascade.release_slot_capacity(slot, res["party_size"])
            expired_reservation_ids.append(res["id"])

    # Sweep 2: lapse ACTIVE non-auto-renew memberships past term_end (cascades).
    for membership in list(db.memberships.values()):
        if (membership["status"] == "ACTIVE"
                and membership["auto_renew"] is False
                and membership["term_end"] is not None
                and current >= membership["term_end"]):
            cascade.lapse_membership(membership)
            lapsed_membership_ids.append(membership["id"])

    data = {
        "now": iso(current),
        "lapsed_membership_ids": lapsed_membership_ids,
        "expired_reservation_ids": expired_reservation_ids,
    }
    return success(data, status=200)
