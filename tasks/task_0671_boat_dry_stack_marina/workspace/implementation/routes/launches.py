from datetime import timedelta

from flask import Blueprint, request

from db import db, iso_ms
from clock import clock, parse_iso
from middleware import require_role
from response import object_response, array_response
from errors import (
    err, ERR_INVALID_STATE, ERR_FORKLIFT_CAPACITY_EXCEEDED,
    ERR_FORKLIFT_SLOT_CONFLICT, ERR_SLOT_NOT_YET_OPEN, ERR_INVALID_REQUEST,
)
from services.common import (
    stamp_create, touch, get_json_body, require_fields, require_string,
    require_bool, parse_pagination, paginate,
)
from services.lookups import get_vessel, get_launch, check_vessel_owner
from services.serialize import launch_view
from services.calculations import compute_launch_fee

launches_bp = Blueprint("launches", __name__)

READ_ROLES = {"DockMaster", "BillingClerk", "BoatOwner"}


def _slot_busy_interval(slot, marina):
    start = parse_iso(slot["window_start"])
    busy_until = parse_iso(slot["busy_until"])
    return start, busy_until


def _forklift_has_conflict(forklift_id, new_start, new_busy_until):
    """A new busy interval [new_start, new_busy_until) must not overlap any
    non-RELEASED slot on the same forklift. Adjacency at busy_until allowed."""
    for s in db.slots.values():
        if s["forklift_id"] != forklift_id:
            continue
        if s["status"] == "RELEASED":
            continue
        ex_start = parse_iso(s["window_start"])
        ex_busy = parse_iso(s["busy_until"])
        # Half-open overlap: new_start < ex_busy AND ex_start < new_busy_until.
        if new_start < ex_busy and ex_start < new_busy_until:
            return True
    return False


@launches_bp.route("/marina/launch-requests", methods=["POST"])
def create_launch():
    user_id, role = require_role({"DockMaster", "BoatOwner"})
    body = get_json_body()
    require_fields(body, ["vessel_id", "requested_window_start"])
    require_string(body["vessel_id"], "vessel_id")
    require_string(body["requested_window_start"], "requested_window_start")
    try:
        parse_iso(body["requested_window_start"])
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "requested_window_start must be an ISO-8601 instant.")
    with_valet_splash = body.get("with_valet_splash", False)
    if with_valet_splash is None:
        with_valet_splash = False
    require_bool(with_valet_splash, "with_valet_splash")
    with db.lock:
        vessel = get_vessel(body["vessel_id"])
        check_vessel_owner(vessel, user_id, role)
        rec = {
            "vessel_id": body["vessel_id"],
            "forklift_slot_id": None,
            "requested_window_start": body["requested_window_start"],
            "with_valet_splash": with_valet_splash,
            "launch_fee_cents": 0,
            "status": "REQUESTED",
        }
        stamp_create(rec)
        db.launches[rec["id"]] = rec
    return object_response(launch_view(rec), 201)


@launches_bp.route("/marina/launch-requests/<launch_id>", methods=["GET"])
def fetch_launch(launch_id):
    require_role(READ_ROLES)
    rec = get_launch(launch_id)
    return object_response(launch_view(rec), 200)


@launches_bp.route("/marina/launch-requests", methods=["GET"])
def list_launches():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.launches.values())
    vessel_id = request.args.get("vessel_id")
    forklift_slot_id = request.args.get("forklift_slot_id")
    status = request.args.get("status")
    if vessel_id is not None:
        records = [r for r in records if r["vessel_id"] == vessel_id]
    if forklift_slot_id is not None:
        records = [r for r in records if r["forklift_slot_id"] == forklift_slot_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response([launch_view(r) for r in page], limit, offset, total)


@launches_bp.route("/marina/launch-requests/<launch_id>/schedule", methods=["POST"])
def schedule_launch(launch_id):
    require_role({"DockMaster"})
    with db.lock:
        launch = get_launch(launch_id)
        vessel = db.vessels[launch["vessel_id"]]
        # Priority 6: state.
        if launch["status"] != "REQUESTED":
            raise err(ERR_INVALID_STATE, "Launch must be REQUESTED to schedule.")
        # Vessel must be RACKED to launch (cross-entity state precondition).
        if vessel["location_status"] != "RACKED":
            raise err(ERR_INVALID_STATE, "Vessel must be RACKED to schedule a launch.")
        marina = db.marinas.get(vessel["marina_id"])
        service_minutes = marina["forklift_service_minutes"] if marina else 30
        buffer_minutes = marina["forklift_buffer_minutes"] if marina else 15

        window_start = parse_iso(launch["requested_window_start"])
        window_end = window_start + timedelta(minutes=service_minutes)
        busy_until = window_start + timedelta(minutes=service_minutes + buffer_minutes)

        # Priority 9: forklift lift-capacity safety. Candidate forklifts are
        # AVAILABLE forklifts in the same marina with sufficient lift capacity.
        capacity_eligible = [
            f for f in db.forklifts.values()
            if f["marina_id"] == vessel["marina_id"]
            and f["status"] == "AVAILABLE"
            and f["max_lift_weight_lbs"] >= vessel["dry_weight_lbs"]
        ]
        if not capacity_eligible:
            raise err(ERR_FORKLIFT_CAPACITY_EXCEEDED,
                      "No AVAILABLE forklift can lift this vessel.")
        # Priority 12: slot conflict. Pick the first eligible forklift (by
        # creation order) without an overlapping busy interval.
        capacity_eligible.sort(key=lambda f: f["_seq"])
        selected = None
        for f in capacity_eligible:
            if not _forklift_has_conflict(f["id"], window_start, busy_until):
                selected = f
                break
        if selected is None:
            raise err(ERR_FORKLIFT_SLOT_CONFLICT,
                      "All capacity-eligible forklifts are busy at the requested window.")

        # Side effects: create the slot, link both ways, compute fee.
        slot = {
            "forklift_id": selected["id"],
            "launch_request_id": launch["id"],
            "window_start": launch["requested_window_start"],
            "window_end": iso_ms(window_end),
            "busy_until": iso_ms(busy_until),
            "status": "BOOKED",
        }
        stamp_create(slot)
        db.slots[slot["id"]] = slot

        launch["forklift_slot_id"] = slot["id"]
        launch["launch_fee_cents"] = compute_launch_fee(
            vessel["loa_ft"], vessel["dry_weight_lbs"], launch["with_valet_splash"])
        launch["status"] = "SCHEDULED"
        touch(launch)
    return object_response(launch_view(launch), 200)


@launches_bp.route("/marina/launch-requests/<launch_id>/unschedule", methods=["POST"])
def unschedule_launch(launch_id):
    require_role({"DockMaster"})
    with db.lock:
        launch = get_launch(launch_id)
        if launch["status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE, "Launch must be SCHEDULED to unschedule.")
        slot = db.slots.get(launch["forklift_slot_id"])
        if slot is not None:
            slot["status"] = "RELEASED"
            slot["launch_request_id"] = None
            touch(slot)
        launch["forklift_slot_id"] = None
        launch["status"] = "REQUESTED"
        touch(launch)
    return object_response(launch_view(launch), 200)


@launches_bp.route("/marina/launch-requests/<launch_id>/splash", methods=["POST"])
def splash_launch(launch_id):
    require_role({"DockMaster"})
    with db.lock:
        launch = get_launch(launch_id)
        if launch["status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE, "Launch must be SCHEDULED to splash.")
        slot = db.slots.get(launch["forklift_slot_id"])
        # Priority 14: splash only once clock >= booked slot window_start.
        if slot is not None and clock.now() < parse_iso(slot["window_start"]):
            raise err(ERR_SLOT_NOT_YET_OPEN, "Slot window has not yet opened.")
        vessel = db.vessels[launch["vessel_id"]]
        # Cascade hop 1: slot COMPLETED.
        if slot is not None:
            slot["status"] = "COMPLETED"
            touch(slot)
        # Cascade hop 2: vessel IN_WATER (rack stays OCCUPIED).
        vessel["location_status"] = "IN_WATER"
        touch(vessel)
        launch["status"] = "SPLASHED"
        touch(launch)
    return object_response(launch_view(launch), 200)


@launches_bp.route("/marina/launch-requests/<launch_id>/haul-back", methods=["POST"])
def haul_back_launch(launch_id):
    require_role({"DockMaster"})
    with db.lock:
        launch = get_launch(launch_id)
        if launch["status"] != "SPLASHED":
            raise err(ERR_INVALID_STATE, "Launch must be SPLASHED to haul back.")
        vessel = db.vessels[launch["vessel_id"]]
        vessel["location_status"] = "RACKED"
        touch(vessel)
        launch["status"] = "RACKED"
        touch(launch)
    return object_response(launch_view(launch), 200)


@launches_bp.route("/marina/launch-requests/<launch_id>/cancel", methods=["POST"])
def cancel_launch(launch_id):
    user_id, role = require_role({"BoatOwner"})
    with db.lock:
        launch = get_launch(launch_id)
        vessel = get_vessel(launch["vessel_id"])
        check_vessel_owner(vessel, user_id, role)
        status = launch["status"]
        if status == "REQUESTED":
            launch["status"] = "CANCELLED"
            touch(launch)
        elif status == "SCHEDULED":
            slot = db.slots.get(launch["forklift_slot_id"])
            if slot is not None:
                slot["status"] = "RELEASED"
                slot["launch_request_id"] = None
                touch(slot)
            launch["forklift_slot_id"] = None
            launch["launch_fee_cents"] = 0
            launch["status"] = "CANCELLED"
            touch(launch)
        else:
            raise err(ERR_INVALID_STATE, "Launch must be REQUESTED or SCHEDULED to cancel.")
    return object_response(launch_view(launch), 200)
