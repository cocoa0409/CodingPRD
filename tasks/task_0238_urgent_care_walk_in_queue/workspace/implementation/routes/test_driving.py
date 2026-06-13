"""Test-driving helpers: clock and queue-depth seed (PRD §3.9)."""
from flask import Blueprint

import clock
import serialize
from db import db, stamp_create
from errors import err
from response import ok_object
from validation import get_json_body
from util import parse_iso
from routes.lookup import get_fk
from services import compute

bp = Blueprint("test_driving", __name__)


@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    # No auth required (bootstrap/test-driving surface).
    body = get_json_body()
    iso = body.get("to_iso8601")
    dt = parse_iso(iso)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be ISO 8601")
    clock.set_clock(dt)
    return ok_object({}, 200)


@bp.route("/_seed/queue-depth", methods=["POST"])
def seed_queue_depth():
    # No auth required (bootstrap/test-driving surface).
    body = get_json_body()
    clinic_id = body.get("clinic_id")
    if clinic_id is None:
        raise err("ERR_INVALID_REQUEST", "clinic_id required")
    clinic = get_fk("clinic", clinic_id)
    count = body.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise err("ERR_INVALID_REQUEST", "count must be a non-negative integer")

    for i in range(count):
        entry = stamp_create({
            "clinic_id": clinic["id"],
            "patient_id": None,
            "arrival_channel": "WALK_IN",
            "chief_complaint": "seeded",
            "reserved_at": None,
            "hold_expires_at": None,
            "esi_level": None,
            "airborne_precaution": False,
            "priority_rank": None,
            "estimated_wait_minutes": None,
            "triaged_at": None,
            "status": "WAITING",
        })
        db.queue_entries[entry["id"]] = entry

    compute.recompute_clinic(clinic)
    return ok_object(serialize.clinic(clinic), 201)
