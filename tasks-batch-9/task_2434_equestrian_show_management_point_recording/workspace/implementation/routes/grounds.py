"""Footing maintenance, ring bookings, calling classes in, carding officials."""

from flask import Blueprint

import calc
import serializers as ser
import services
import validate as v
from auth import endpoint
from core import (
    COVERAGE_CHECKIN_LEAD_MINUTES,
    MAX_OFFICIAL_DAILY_MINUTES,
    MIN_FOOTING_SCORE,
    MIN_OFFICIAL_LICENSE_LEVEL,
    OFFICIAL_ROLES,
    REQUIRED_OFFICIALS,
    WARMUP_LEAD_MINUTES,
    WELFARE_STRIKE_LIMIT,
    assignments_of_slot,
    class_entries_of_class,
    coverage_of_show,
    db,
    division_of_class,
    find,
    new_row,
    now_clock,
    show_of_ring,
    slots_of_class,
    timedelta_minutes,
    touch,
)
from errors import ApiError
from response import object_response

bp = Blueprint("grounds", __name__)


@bp.post("/rings/<ring_id>/footing-maintenance")
@endpoint("GroundsManager")
def footing_maintenance(ring_id):
    ring = find(db.rings, ring_id, "ERR_RING_NOT_FOUND")
    payload = v.body()
    start_utc = v.req_dt(payload, "start_utc")
    duration_minutes = v.req_int(payload, "duration_minutes", minimum=1)
    new_score = v.req_int(payload, "new_footing_condition_score", minimum=0, maximum=100)

    unsafe = new_score < MIN_FOOTING_SCORE
    if ring["status"] == "MAINTENANCE_HOLD" and unsafe:
        raise ApiError("ERR_RING_NOT_AVAILABLE")

    end_utc = start_utc + timedelta_minutes(duration_minutes)
    show = show_of_ring(ring)
    if show is not None and (start_utc < show["start_utc"] or end_utc > show["end_utc"]):
        raise ApiError("ERR_SLOT_OUTSIDE_SHOW_WINDOW")
    if not unsafe and services.ring_overlap(ring, start_utc, end_utc):
        raise ApiError("ERR_RING_SLOT_OVERLAP")

    new_row(
        db.slots,
        ring_id=ring["id"],
        class_id=None,
        slot_type="MAINTENANCE",
        start_utc=start_utc,
        duration_minutes=duration_minutes,
        end_utc=end_utc,
        warmup_start_utc=start_utc - timedelta_minutes(WARMUP_LEAD_MINUTES),
        order_index=None,
        status="SCHEDULED",
    )

    ring["footing_condition_score"] = new_score
    touch(ring)
    if unsafe:
        services.footing_cascade(ring)
    elif ring["status"] == "MAINTENANCE_HOLD":
        ring["status"] = "AVAILABLE"
    services.recompute_ring_layout(ring)
    return object_response(ser.ser_ring(ring))


@bp.post("/ring-slots")
@endpoint("RingMaster")
def book_ring_slot():
    raw = v.raw_body()
    ring_key = v.fk_candidate(raw, "ring_id")
    if ring_key is not None:
        find(db.rings, ring_key, "ERR_RING_NOT_FOUND")
    class_key = v.fk_candidate(raw, "class_id")
    if class_key is not None:
        find(db.classes, class_key, "ERR_CLASS_NOT_FOUND")

    payload = v.body()
    ring_id = v.req_str(payload, "ring_id")
    class_id = v.req_str(payload, "class_id")
    start_utc = v.req_dt(payload, "start_utc")
    expected_ring_version = v.req_int(payload, "expected_ring_version")

    ring = find(db.rings, ring_id, "ERR_RING_NOT_FOUND")
    cls = find(db.classes, class_id, "ERR_CLASS_NOT_FOUND")

    if expected_ring_version != int(ring["version"]):
        raise ApiError("ERR_STALE_VERSION")

    # A class already holding a live occupancy is reported as double-booked; the
    # plain state check then catches classes that never reached OPEN.
    for slot in slots_of_class(cls["id"]):
        if slot["status"] in ("SCHEDULED", "RUNNING", "COMPLETED"):
            raise ApiError("ERR_CLASS_ALREADY_SCHEDULED")
    if cls["status"] != "OPEN":
        raise ApiError("ERR_CLASS_NOT_OPEN")

    division = division_of_class(cls)
    rows = class_entries_of_class(cls["id"])
    projected = calc.count_class_entries(rows, calc.PROJECTED_STATUSES)
    estimated = calc.duration_estimate(cls, division, ring, projected)
    end_utc = start_utc + timedelta_minutes(estimated)

    show = show_of_ring(ring)
    if show is not None and (start_utc < show["start_utc"] or end_utc > show["end_utc"]):
        raise ApiError("ERR_SLOT_OUTSIDE_SHOW_WINDOW")
    if services.ring_overlap(ring, start_utc, end_utc):
        raise ApiError("ERR_RING_SLOT_OVERLAP")

    slot = new_row(
        db.slots,
        ring_id=ring["id"],
        class_id=cls["id"],
        slot_type="CLASS",
        start_utc=start_utc,
        duration_minutes=estimated,
        end_utc=end_utc,
        warmup_start_utc=start_utc - timedelta_minutes(WARMUP_LEAD_MINUTES),
        order_index=None,
        status="SCHEDULED",
    )
    cls["estimated_minutes"] = estimated
    cls["status"] = "SCHEDULED"
    touch(cls)
    touch(ring)
    services.recompute_ring_layout(ring)
    return object_response(ser.ser_slot(slot), 201)


@bp.post("/ring-slots/<slot_id>/start")
@endpoint("RingMaster")
def start_ring_slot(slot_id):
    slot = find(db.slots, slot_id, "ERR_SLOT_NOT_FOUND")
    if slot["status"] != "SCHEDULED" or slot["slot_type"] != "CLASS":
        raise ApiError("ERR_SLOT_NOT_SCHEDULED")
    ring = db.rings.get(slot["ring_id"])
    if ring is None or ring["status"] != "AVAILABLE":
        raise ApiError("ERR_RING_NOT_AVAILABLE")
    show = show_of_ring(ring)
    if show is None or show["license_status"] != "APPROVED":
        raise ApiError("ERR_SHOW_LICENSE_NOT_APPROVED")

    if int(ring["footing_condition_score"]) < MIN_FOOTING_SCORE:
        raise ApiError("ERR_FOOTING_UNSAFE")

    covered = False
    for shift in coverage_of_show(show["id"]):
        if shift["coverage_type"] != "VETERINARIAN" or shift["status"] != "ACTIVE":
            continue
        if shift["start_utc"] <= slot["start_utc"] and slot["end_utc"] <= shift["end_utc"]:
            covered = True
            break
    if not covered:
        raise ApiError("ERR_VET_COVERAGE_MISSING")

    required = REQUIRED_OFFICIALS[show["competition_level"]]
    for role, count in required.items():
        if count <= 0:
            continue
        holders = {
            a["official_id"]
            for a in assignments_of_slot(slot["id"])
            if a["status"] == "ACTIVE" and a["official_role"] == role
        }
        if len(holders) < count:
            raise ApiError("ERR_OFFICIALS_REQUIREMENT_UNMET")

    if int(show["welfare_strike_count"]) >= WELFARE_STRIKE_LIMIT:
        raise ApiError("ERR_WELFARE_STRIKE_LIMIT")

    slot["status"] = "RUNNING"
    touch(slot)
    cls = db.classes.get(slot["class_id"])
    if cls is not None:
        cls["status"] = "IN_PROGRESS"
        touch(cls)
    return object_response(ser.ser_slot(slot))


@bp.post("/official-assignments")
@endpoint("ShowSecretary")
def card_official():
    raw = v.raw_body()
    official_key = v.fk_candidate(raw, "official_id")
    if official_key is not None:
        find(db.officials, official_key, "ERR_OFFICIAL_NOT_FOUND")
    slot_key = v.fk_candidate(raw, "slot_id")
    if slot_key is not None:
        find(db.slots, slot_key, "ERR_SLOT_NOT_FOUND")

    payload = v.body()
    official_id = v.req_str(payload, "official_id")
    slot_id = v.req_str(payload, "slot_id")
    official_role = v.req_enum(payload, "official_role", OFFICIAL_ROLES)

    official = find(db.officials, official_id, "ERR_OFFICIAL_NOT_FOUND")
    slot = find(db.slots, slot_id, "ERR_SLOT_NOT_FOUND")

    ring = db.rings.get(slot["ring_id"])
    show = show_of_ring(ring) if ring is not None else None
    cls = db.classes.get(slot["class_id"]) if slot.get("class_id") else None
    division = division_of_class(cls) if cls is not None else None

    if official_role not in official["license_roles"]:
        raise ApiError("ERR_OFFICIAL_LICENSE_INSUFFICIENT")
    if division is not None and division["discipline"] not in official["licensed_disciplines"]:
        raise ApiError("ERR_OFFICIAL_LICENSE_INSUFFICIENT")
    if show is not None:
        minimum = MIN_OFFICIAL_LICENSE_LEVEL[show["competition_level"]]
        if int(official["license_level"]) < minimum:
            raise ApiError("ERR_OFFICIAL_LICENSE_INSUFFICIENT")
    if slot["start_utc"] >= official["license_expires_on"]:
        raise ApiError("ERR_OFFICIAL_LICENSE_INSUFFICIENT")

    trainer = official.get("affiliated_trainer_name")
    if trainer and cls is not None:
        for class_entry in class_entries_of_class(cls["id"]):
            if class_entry["status"] not in ("ENTERED", "CONFIRMED"):
                continue
            entry = db.entries.get(class_entry["entry_id"])
            rider = db.riders.get(entry["rider_id"]) if entry else None
            if rider is not None and rider.get("trainer_name") == trainer:
                raise ApiError("ERR_OFFICIAL_CONFLICT_OF_INTEREST")

    if services.official_overlap(official, slot):
        raise ApiError("ERR_OFFICIAL_TIME_CONFLICT")

    minutes = services.slot_minutes(slot)
    if int(official["assigned_minutes"]) + minutes > MAX_OFFICIAL_DAILY_MINUTES:
        raise ApiError("ERR_OFFICIAL_LOAD_EXCEEDED")

    assignment = new_row(
        db.assignments,
        official_id=official["id"],
        slot_id=slot["id"],
        official_role=official_role,
        status="ACTIVE",
    )
    official["assigned_minutes"] = int(official["assigned_minutes"]) + minutes
    touch(official)
    return object_response(ser.ser_assignment(assignment), 201)


@bp.post("/coverage-shifts/<shift_id>/activate")
@endpoint("GroundsManager")
def activate_coverage_shift(shift_id):
    shift = find(db.coverage_shifts, shift_id, "ERR_COVERAGE_SHIFT_NOT_FOUND")
    if shift["status"] != "SCHEDULED":
        raise ApiError("ERR_COVERAGE_SHIFT_NOT_SCHEDULED")
    if now_clock() < shift["start_utc"] - timedelta_minutes(COVERAGE_CHECKIN_LEAD_MINUTES):
        raise ApiError("ERR_COVERAGE_CHECKIN_TOO_EARLY")
    shift["status"] = "ACTIVE"
    touch(shift)
    return object_response(ser.ser_coverage(shift))
