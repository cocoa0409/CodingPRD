"""Tank config + operational axis; sanitation cycles + sanitation axis."""
from datetime import timedelta

from flask import Blueprint, request

import errors
import serializers
from clock import clock
from db import db, stamp_create, touch
from helpers import get_json_body, require_fields, parse_pagination, paginate
from middleware import authenticate, require_role
from response import success

bp = Blueprint("tanks", __name__)

ACTIVE_BOOKING_STATES = {"RESERVED", "CONFIRMED", "RESCHEDULED", "CHECKED_IN"}


# ----------------------------------------------------------------- tanks
@bp.route("/tanks", methods=["POST"])
def create_tank():
    principal = authenticate()
    require_role(principal, {"Admin"})
    body = get_json_body()
    require_fields(body, ["name", "capacity_kind"])
    capacity_kind = body["capacity_kind"]
    if capacity_kind not in ("SINGLE", "DUAL"):
        raise errors.invalid_request("capacity_kind must be SINGLE or DUAL.")
    buffer_minutes = body.get("turnover_buffer_minutes", 30)
    if not isinstance(buffer_minutes, int) or isinstance(buffer_minutes, bool):
        raise errors.invalid_request("turnover_buffer_minutes must be an integer.")
    if buffer_minutes < 0:
        raise errors.validation_range("turnover_buffer_minutes must be >= 0.")
    record = {
        "name": body["name"],
        "capacity_kind": capacity_kind,
        "turnover_buffer_minutes": buffer_minutes,
        "operational_status": "IN_SERVICE",
        "sanitation_status": "CLEAN",
    }
    stamp_create(record)
    db.tanks[record["id"]] = record
    return success(serializers.tank_out(record), status=201)


@bp.route("/tanks/<tid>", methods=["GET"])
def get_tank(tid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    tank = db.tanks.get(tid)
    if tank is None:
        raise errors.not_found("Tank not found.")
    return success(serializers.tank_out(tank), status=200)


@bp.route("/tanks", methods=["GET"])
def list_tanks():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    records = list(db.tanks.values())
    capacity_kind = request.args.get("capacity_kind")
    if capacity_kind is not None:
        records = [r for r in records if r["capacity_kind"] == capacity_kind]
    page, meta = paginate(records, limit, offset)
    return success([serializers.tank_out(r) for r in page], status=200, pagination=meta)


@bp.route("/tanks/<tid>/maintenance", methods=["POST"])
def tank_maintenance(tid):
    principal = authenticate()
    require_role(principal, {"Admin"})
    tank = _get_tank(tid)
    if tank["operational_status"] != "IN_SERVICE":
        raise errors.invalid_state("Tank is not IN_SERVICE.")
    tank["operational_status"] = "MAINTENANCE"
    touch(tank)
    return success(serializers.tank_out(tank), status=200)


@bp.route("/tanks/<tid>/return-to-service", methods=["POST"])
def tank_return(tid):
    principal = authenticate()
    require_role(principal, {"Admin"})
    tank = _get_tank(tid)
    if tank["operational_status"] != "MAINTENANCE":
        raise errors.invalid_state("Tank is not MAINTENANCE.")
    tank["operational_status"] = "IN_SERVICE"
    touch(tank)
    return success(serializers.tank_out(tank), status=200)


@bp.route("/tanks/<tid>/retire", methods=["POST"])
def tank_retire(tid):
    principal = authenticate()
    require_role(principal, {"Admin"})
    tank = _get_tank(tid)
    if tank["operational_status"] == "RETIRED":
        raise errors.invalid_state("Tank already RETIRED.")
    # Business constraint: no live booking on the tank.
    for b in db.bookings.values():
        if b["tank_id"] == tid and b["status"] in ACTIVE_BOOKING_STATES:
            raise errors.tank_has_bookings()
    tank["operational_status"] = "RETIRED"
    touch(tank)
    return success(serializers.tank_out(tank), status=200)


# ----------------------------------------------------------------- sanitation cycles
@bp.route("/sanitation-cycles", methods=["POST"])
def create_sanitation_cycle():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    body = get_json_body()
    require_fields(body, ["tank_id", "kind"])
    tank = db.tanks.get(body["tank_id"])
    if tank is None:
        raise errors.not_found("Tank not found.")
    booking_id = body.get("booking_id")
    if booking_id is not None and db.bookings.get(booking_id) is None:
        raise errors.not_found("Booking not found.")
    kind = body["kind"]
    if kind not in ("TURNOVER", "DEEP_CLEAN"):
        raise errors.invalid_request("kind must be TURNOVER or DEEP_CLEAN.")
    duration = body.get("duration_minutes")
    if duration is None:
        duration = tank["turnover_buffer_minutes"]
    if not isinstance(duration, int) or isinstance(duration, bool):
        raise errors.invalid_request("duration_minutes must be an integer.")
    if duration < 0:
        raise errors.invalid_request("duration_minutes must be >= 0.")
    cycle = start_sanitation_cycle(tank, kind=kind, booking_id=booking_id,
                                   duration_minutes=duration)
    return success(serializers.sanitation_out(cycle), status=201)


@bp.route("/sanitation-cycles/<cid>", methods=["GET"])
def get_sanitation_cycle(cid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    cycle = db.sanitation_cycles.get(cid)
    if cycle is None:
        raise errors.not_found("Sanitation cycle not found.")
    return success(serializers.sanitation_out(cycle), status=200)


@bp.route("/sanitation-cycles", methods=["GET"])
def list_sanitation_cycles():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    limit, offset = parse_pagination()
    records = list(db.sanitation_cycles.values())
    tank_id = request.args.get("tank_id")
    booking_id = request.args.get("booking_id")
    if tank_id is not None:
        records = [r for r in records if r["tank_id"] == tank_id]
    if booking_id is not None:
        records = [r for r in records if r["booking_id"] == booking_id]
    page, meta = paginate(records, limit, offset)
    return success([serializers.sanitation_out(r) for r in page], status=200, pagination=meta)


@bp.route("/sanitation-cycles/<cid>/complete", methods=["POST"])
def complete_sanitation_cycle(cid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    cycle = db.sanitation_cycles.get(cid)
    if cycle is None:
        raise errors.not_found("Sanitation cycle not found.")
    if cycle["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Sanitation cycle is not IN_PROGRESS.")
    now = clock.now()
    if now < cycle["ends_utc"]:
        raise errors.timing_not_allowed("Sanitation cannot complete before ends_utc.")
    cycle["status"] = "COMPLETED"
    touch(cycle)
    tank = db.tanks.get(cycle["tank_id"])
    if tank is not None:
        # Back to CLEAN only if no other IN_PROGRESS cycle remains on the tank.
        remaining = any(
            c["tank_id"] == tank["id"] and c["status"] == "IN_PROGRESS"
            for c in db.sanitation_cycles.values()
        )
        if not remaining:
            tank["sanitation_status"] = "CLEAN"
            touch(tank)
    return success(serializers.sanitation_out(cycle), status=200)


# ----------------------------------------------------------------- helpers
def _get_tank(tid):
    tank = db.tanks.get(tid)
    if tank is None:
        raise errors.not_found("Tank not found.")
    return tank


def start_sanitation_cycle(tank, kind, booking_id, duration_minutes):
    """Create an IN_PROGRESS cycle and flip the tank to IN_CYCLE.

    Shared by the manual-create endpoint and the booking-completion cascade.
    """
    now = clock.now()
    cycle = {
        "tank_id": tank["id"],
        "booking_id": booking_id,
        "kind": kind,
        "status": "IN_PROGRESS",
        "started_utc": now,
        "ends_utc": now + timedelta(minutes=duration_minutes),
        "duration_minutes": duration_minutes,
    }
    stamp_create(cycle)
    db.sanitation_cycles[cycle["id"]] = cycle
    if tank["sanitation_status"] != "IN_CYCLE":
        tank["sanitation_status"] = "IN_CYCLE"
        touch(tank)
    return cycle
