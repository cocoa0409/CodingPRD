"""TimeSlot routes (PRD §3.1)."""
from datetime import datetime, timezone

from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from response import success, list_success
from services import serialize
from services.common import (
    new_record, get_body, get_or_404, paginate, req_str, req_int,
)

bp = Blueprint("time_slots", __name__)

READ_ROLES = {"GardenAdmin", "GardenStaff", "RentalCoordinator",
              "DevelopmentOfficer", "Visitor"}


def parse_dt(value, field):
    if not isinstance(value, str):
        raise errors.validation(f"{field} must be an ISO 8601 string")
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise errors.validation(f"{field} is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(body, field):
    if field not in body or body[field] is None:
        raise errors.validation(f"Missing required field: {field}")
    return parse_dt(body[field], field)


@bp.route("/v1/time-slots", methods=["POST"])
def create_time_slot():
    _, role = get_identity()
    require_role(role, {"GardenAdmin", "GardenStaff"})
    body = get_body()
    garden_id = req_str(body, "garden_id")
    starts_at = req_dt(body, "starts_at")
    ends_at = req_dt(body, "ends_at")
    capacity = req_int(body, "capacity", min_value=1)
    ga_price_cents = req_int(body, "ga_price_cents", min_value=0)
    get_or_404(db.gardens, garden_id)
    # Time window well-formed (PRD §2.9 / §3.1): ends_at strictly after starts_at.
    if ends_at <= starts_at:
        raise errors.invalid_window()
    rec = new_record({
        "garden_id": garden_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
        "ga_price_cents": ga_price_cents,
        "held_count": 0,
        "status": "OPEN",
    })
    db.time_slots[rec["id"]] = rec
    return success(serialize.time_slot(rec), status=201)


@bp.route("/v1/time-slots/<slot_id>", methods=["GET"])
def read_time_slot(slot_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.time_slots, slot_id)
    return success(serialize.time_slot(rec), status=200)


@bp.route("/v1/time-slots", methods=["GET"])
def list_time_slots():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    garden_id = request.args.get("garden_id")
    status = request.args.get("status")
    records = list(db.time_slots.values())
    if garden_id is not None:
        records = [r for r in records if r["garden_id"] == garden_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.time_slot(r) for r in page],
                        limit, offset, total)
