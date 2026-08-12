"""FixerProfile, FixerSkill, and FixerShift endpoints."""

from datetime import timedelta

from flask import Blueprint, Response, g

import db
import serializers as ser
import services
from errors import (
    ERR_EVENT_NOT_FOUND,
    ERR_EVENT_PHASE_FORBIDS,
    ERR_EVENT_STATION_MISMATCH,
    ERR_FIXER_NOT_FOUND,
    ERR_FIXER_SUSPENDED,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INDUCTION_EXPIRED,
    ERR_INVALID_FIXER_STATE,
    ERR_INVALID_SHIFT_STATE,
    ERR_ITEMS_IN_FLIGHT,
    ERR_RELIABILITY_TOO_LOW,
    ERR_SHIFT_NOT_FOUND,
    ERR_SHIFT_NOT_IN_WINDOW,
    ERR_SHIFT_OVERLAP,
    ERR_SHIFT_TOO_LONG,
    ERR_SKILL_DUPLICATE,
    ERR_SKILL_NOT_FOUND,
    ERR_STATION_AT_CAPACITY,
    ERR_STATION_INTERVAL_CAPACITY_EXCEEDED,
    ERR_STATION_NOT_FOUND,
    ERR_VALIDATION,
    raise_err,
)
from middleware import require_roles
from response import success
from util import (
    as_bool,
    as_dt,
    as_enum,
    as_int,
    as_str,
    body,
    list_response,
    opt,
    req,
)

bp = Blueprint("fixers", __name__)

ALL_ROLES = ("Coordinator", "IntakeVolunteer", "Fixer", "SafetyOfficer")
SKILL_CATEGORIES = ("ELECTRONICS", "TEXTILE", "BIKE")


def get_fixer_or_404(fixer_id):
    fixer = db.fixers.get(fixer_id)
    if fixer is None:
        raise_err(ERR_FIXER_NOT_FOUND, "FixerProfile %s does not exist" % fixer_id)
    return fixer


def get_shift_or_404(shift_id):
    shift = db.shifts.get(shift_id)
    if shift is None:
        raise_err(ERR_SHIFT_NOT_FOUND, "FixerShift %s does not exist" % shift_id)
    return shift


# ---------------------------------------------------------- fixer profiles ---

@bp.post("/api/fixer-profiles")
@require_roles("Coordinator")
def create_fixer():
    b = body()
    display_name = as_str(req(b, "display_name"), "display_name")
    email = as_str(req(b, "email"), "email", required_len=True)
    induction = as_dt(req(b, "safety_induction_completed_at"), "safety_induction_completed_at")
    for f in db.fixers.values():
        if f["email"] == email:
            raise_err(ERR_VALIDATION, "A fixer with this email already exists")
    rec = db.stamp_new(
        {
            "display_name": display_name,
            "email": email,
            "status": "ACTIVE",
            "safety_induction_completed_at": induction,
        }
    )
    db.fixers[rec["id"]] = rec
    return success(ser.fixer(rec), 201)


@bp.get("/api/fixer-profiles")
@require_roles(*ALL_ROLES)
def list_fixers():
    return list_response(db.fixers.values(), ser.fixer, [("status", "status")])


@bp.get("/api/fixer-profiles/<fixer_id>")
@require_roles(*ALL_ROLES)
def get_fixer(fixer_id):
    return success(ser.fixer(get_fixer_or_404(fixer_id)), 200)


@bp.post("/api/fixer-profiles/<fixer_id>/suspend")
@require_roles("SafetyOfficer")
def suspend_fixer(fixer_id):
    fixer = get_fixer_or_404(fixer_id)
    if fixer["status"] != "ACTIVE":
        raise_err(ERR_INVALID_FIXER_STATE, "Only an ACTIVE fixer can be suspended")
    services.suspend_fixer(fixer)
    return success(ser.fixer(fixer), 200)


@bp.post("/api/fixer-profiles/<fixer_id>/reinstate")
@require_roles("SafetyOfficer")
def reinstate_fixer(fixer_id):
    fixer = get_fixer_or_404(fixer_id)
    if fixer["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_FIXER_STATE, "Only a SUSPENDED fixer can be reinstated")
    if services.reliability(fixer["id"]) < services.RELIABILITY_THRESHOLD:
        raise_err(ERR_RELIABILITY_TOO_LOW, "Reliability score is below 40")
    fixer["status"] = "ACTIVE"
    db.touch(fixer)
    return success(ser.fixer(fixer), 200)


@bp.post("/api/fixer-profiles/<fixer_id>/deactivate")
@require_roles("Coordinator")
def deactivate_fixer(fixer_id):
    fixer = get_fixer_or_404(fixer_id)
    if fixer["status"] != "ACTIVE":
        raise_err(ERR_INVALID_FIXER_STATE, "Only an ACTIVE fixer can be deactivated")
    for s in db.shifts.values():
        if s["fixer_id"] == fixer["id"] and s["status"] in ("SIGNED_UP", "CONFIRMED", "CHECKED_IN"):
            raise_err(ERR_ITEMS_IN_FLIGHT, "Fixer holds non-terminal shifts")
    for it in db.items.values():
        if it["assigned_fixer_id"] == fixer["id"] and it["status"] in ("ASSIGNED", "IN_REPAIR"):
            raise_err(ERR_ITEMS_IN_FLIGHT, "Fixer has items assigned")
    fixer["status"] = "INACTIVE"
    db.touch(fixer)
    return success(ser.fixer(fixer), 200)


# -------------------------------------------------------------- fixer skills ---

@bp.post("/api/fixer-skills")
@require_roles("Coordinator")
def create_skill():
    b = body()
    fixer_id = as_str(req(b, "fixer_id"), "fixer_id")
    get_fixer_or_404(fixer_id)
    category = as_enum(req(b, "category"), "category", SKILL_CATEGORIES)
    level = as_int(req(b, "level"), "level", lo=1, hi=5)
    certified = as_bool(opt(b, "certified", False), "certified")
    for sk in db.skills.values():
        if sk["fixer_id"] == fixer_id and sk["category"] == category:
            raise_err(ERR_SKILL_DUPLICATE, "Fixer already holds a skill in this category")
    rec = db.stamp_new(
        {"fixer_id": fixer_id, "category": category, "level": level, "certified": certified},
        with_version=False,
    )
    db.skills[rec["id"]] = rec
    return success(ser.skill(rec), 201)


@bp.get("/api/fixer-skills")
@require_roles(*ALL_ROLES)
def list_skills():
    return list_response(
        db.skills.values(),
        ser.skill,
        [("fixer_id", "fixer_id"), ("category", "category")],
    )


@bp.get("/api/fixer-skills/<skill_id>")
@require_roles(*ALL_ROLES)
def get_skill(skill_id):
    rec = db.skills.get(skill_id)
    if rec is None:
        raise_err(ERR_SKILL_NOT_FOUND, "FixerSkill %s does not exist" % skill_id)
    return success(ser.skill(rec), 200)


@bp.delete("/api/fixer-skills/<skill_id>")
@require_roles("Coordinator")
def delete_skill(skill_id):
    rec = db.skills.get(skill_id)
    if rec is None:
        raise_err(ERR_SKILL_NOT_FOUND, "FixerSkill %s does not exist" % skill_id)
    del db.skills[skill_id]
    return Response(status=204)


# -------------------------------------------------------------- fixer shifts ---

@bp.post("/api/fixer-shifts")
@require_roles("Coordinator", "Fixer")
def create_shift():
    b = body()
    fixer_id = as_str(req(b, "fixer_id"), "fixer_id")
    # Ownership (priority 2): a Fixer may only sign up for themselves.
    if g.role == "Fixer" and fixer_id != g.user_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "A fixer may only sign up for themselves")
    # Existence (priority 3), body FKs in declared order.
    fixer = get_fixer_or_404(fixer_id)
    station_id = as_str(req(b, "station_id"), "station_id")
    station = db.stations.get(station_id)
    if station is None:
        raise_err(ERR_STATION_NOT_FOUND, "Station %s does not exist" % station_id)
    event_id = as_str(req(b, "event_id"), "event_id")
    if event_id not in db.events:
        raise_err(ERR_EVENT_NOT_FOUND, "RepairEvent %s does not exist" % event_id)
    start_raw = as_dt(req(b, "start_time"), "start_time")
    end_raw = as_dt(req(b, "end_time"), "end_time")
    start = db.parse_dt(start_raw)
    end = db.parse_dt(end_raw)

    # Priority 6: shift duration shape.
    duration = (end - start).total_seconds()
    if not (0 < duration <= 21600):
        raise_err(ERR_SHIFT_TOO_LONG, "Shift must last > 0 and <= 21600 seconds")

    # Priority 7: fixer double-booking, HALF-OPEN [start, end) overlap.
    for s in db.shifts.values():
        if s["fixer_id"] != fixer_id or s["status"] == "CANCELLED":
            continue
        s_start = db.parse_dt(s["start_time"])
        s_end = db.parse_dt(s["end_time"])
        if start < s_end and s_start < end:
            raise_err(ERR_SHIFT_OVERLAP, "Shift overlaps an existing shift of this fixer")

    # Priority 8: station interval capacity, CLOSED-interval overlap counting.
    overlapping = 0
    for s in db.shifts.values():
        if s["station_id"] != station_id or s["status"] == "CANCELLED":
            continue
        s_start = db.parse_dt(s["start_time"])
        s_end = db.parse_dt(s["end_time"])
        if start <= s_end and s_start <= end:
            overlapping += 1
    if overlapping >= station["capacity"]:
        raise_err(
            ERR_STATION_INTERVAL_CAPACITY_EXCEEDED,
            "Station shift-interval capacity reached",
        )

    # Priority 10: reliability gate, then active-fixer requirement.
    if services.reliability(fixer_id) < services.RELIABILITY_THRESHOLD:
        raise_err(ERR_RELIABILITY_TOO_LOW, "Reliability score is below 40")
    if fixer["status"] != "ACTIVE":
        raise_err(ERR_FIXER_SUSPENDED, "Fixer is not ACTIVE")

    # Priority 11: cross-FK consistency.
    if event_id != station["event_id"]:
        raise_err(ERR_EVENT_STATION_MISMATCH, "Shift event does not match station event")

    rec = db.stamp_new(
        {
            "fixer_id": fixer_id,
            "station_id": station_id,
            "event_id": event_id,
            "start_time": start_raw,
            "end_time": end_raw,
            "status": "SIGNED_UP",
            "checked_in_at": None,
        }
    )
    db.shifts[rec["id"]] = rec
    return success(ser.shift(rec), 201)


@bp.get("/api/fixer-shifts")
@require_roles(*ALL_ROLES)
def list_shifts():
    return list_response(
        db.shifts.values(),
        ser.shift,
        [
            ("fixer_id", "fixer_id"),
            ("station_id", "station_id"),
            ("event_id", "event_id"),
            ("status", "status"),
        ],
    )


@bp.get("/api/fixer-shifts/<shift_id>")
@require_roles(*ALL_ROLES)
def get_shift(shift_id):
    return success(ser.shift(get_shift_or_404(shift_id)), 200)


@bp.post("/api/fixer-shifts/<shift_id>/confirm")
@require_roles("Coordinator")
def confirm_shift(shift_id):
    shift = get_shift_or_404(shift_id)
    if shift["status"] != "SIGNED_UP":
        raise_err(ERR_INVALID_SHIFT_STATE, "Only a SIGNED_UP shift can be confirmed")
    shift["status"] = "CONFIRMED"
    db.touch(shift)
    return success(ser.shift(shift), 200)


@bp.post("/api/fixer-shifts/<shift_id>/check-in")
@require_roles("Coordinator", "Fixer")
def check_in_shift(shift_id):
    shift = get_shift_or_404(shift_id)
    if g.role == "Fixer" and shift["fixer_id"] != g.user_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "A fixer may only check in to their own shift")
    # State (priority 4).
    if shift["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_SHIFT_STATE, "Only a CONFIRMED shift can be checked in")
    event = db.events[shift["event_id"]]
    if event["status"] not in ("PUBLISHED", "INTAKE_OPEN", "REPAIR_ACTIVE"):
        raise_err(ERR_EVENT_PHASE_FORBIDS, "Event phase forbids check-in")
    # Safety gate (priority 5): induction validity.
    fixer = db.fixers[shift["fixer_id"]]
    induction = db.parse_dt(fixer["safety_induction_completed_at"])
    if induction + timedelta(days=365) <= db.clock.current:
        raise_err(ERR_INDUCTION_EXPIRED, "Safety induction has expired")
    # Check-in window (priority 9): start_time <= now < end_time.
    if not (db.parse_dt(shift["start_time"]) <= db.clock.current < db.parse_dt(shift["end_time"])):
        raise_err(ERR_SHIFT_NOT_IN_WINDOW, "Current time is outside the shift window")
    # Skill/active constraints (priority 10).
    if fixer["status"] != "ACTIVE":
        raise_err(ERR_FIXER_SUSPENDED, "Fixer is not ACTIVE")
    # Capacity (priority 12, always last).
    station = db.stations[shift["station_id"]]
    if services.checked_in_count(station["id"]) >= station["capacity"]:
        raise_err(ERR_STATION_AT_CAPACITY, "Station is at capacity")
    shift["status"] = "CHECKED_IN"
    shift["checked_in_at"] = db.clock.now_iso()
    db.touch(shift)
    return success(ser.shift(shift), 200)


@bp.post("/api/fixer-shifts/<shift_id>/check-out")
@require_roles("Coordinator", "Fixer")
def check_out_shift(shift_id):
    shift = get_shift_or_404(shift_id)
    if g.role == "Fixer" and shift["fixer_id"] != g.user_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "A fixer may only check out of their own shift")
    b = body()
    completion = as_bool(req(b, "completion"), "completion")
    if shift["status"] != "CHECKED_IN":
        raise_err(ERR_INVALID_SHIFT_STATE, "Only a CHECKED_IN shift can be checked out")
    shift["status"] = "COMPLETED" if completion else "LEFT_EARLY"
    db.touch(shift)
    station = db.stations.get(shift["station_id"])
    if station is not None:
        services.auto_pause_if_empty(station)
    return success(ser.shift(shift), 200)


@bp.post("/api/fixer-shifts/<shift_id>/cancel")
@require_roles("Coordinator", "Fixer")
def cancel_shift(shift_id):
    shift = get_shift_or_404(shift_id)
    if g.role == "Fixer" and shift["fixer_id"] != g.user_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "A fixer may only cancel their own shift")
    if shift["status"] not in ("SIGNED_UP", "CONFIRMED"):
        raise_err(ERR_INVALID_SHIFT_STATE, "Only a SIGNED_UP or CONFIRMED shift can be cancelled")
    shift["status"] = "CANCELLED"
    db.touch(shift)
    return success(ser.shift(shift), 200)
