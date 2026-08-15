"""Bases, aircraft, crew members, crew shifts, and the test-driving clock."""

from flask import Blueprint

import calc
from core import (
    ERR_DUTY_LIMIT_EXCEEDED, ERR_FORBIDDEN, ERR_INSUFFICIENT_REST,
    ERR_INVALID_STATE, ERR_SHIFT_OVERLAP, ERR_VALIDATION, db, fail, get_body,
    list_response, must_exist, now_iso, ok_object, parse_dt, render_ts,
    require_roles, stamp_new, touch, v_dt, v_enum, v_str,
)
from serialize import (
    ser_aircraft, ser_base, ser_crew_member, ser_crew_shift,
)

bp = Blueprint("admin", __name__)

ALL_ROLES = ("OpsAdmin", "Dispatcher", "MedicalDirector", "FlightCrew",
             "BillingSpecialist", "QaReviewer")

AIRCRAFT_CLASSES = {"ROTOR_WING", "FIXED_WING"}
MEDICAL_CONFIGS = {"BLS_CAPABLE", "ALS_CAPABLE", "CCT_CAPABLE"}
AIRCRAFT_STATUSES = {"AVAILABLE", "ASSIGNED", "MAINTENANCE"}
CREW_ROLES = {"PILOT", "NURSE", "PARAMEDIC"}
CREW_STATUSES = {"ACTIVE", "REMEDIATION_HOLD", "INACTIVE"}
SHIFT_STATUSES = {"OPEN", "CLOSED"}


# ---------------------------------------------------------------------------
# Bases
# ---------------------------------------------------------------------------


@bp.route("/air-ambulance/bases", methods=["POST"])
def create_base():
    require_roles("OpsAdmin")
    body = get_body()
    rec = stamp_new({
        "name": v_str(body, "name"),
        "region": v_str(body, "region"),
    })
    db.bases[rec["id"]] = rec
    return ok_object(ser_base(rec), 201)


@bp.route("/air-ambulance/bases/<rid>", methods=["GET"])
def get_base(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.bases, rid, "Base")
    return ok_object(ser_base(rec))


# ---------------------------------------------------------------------------
# Aircraft
# ---------------------------------------------------------------------------


@bp.route("/air-ambulance/aircraft", methods=["POST"])
def create_aircraft():
    require_roles("OpsAdmin")
    body = get_body()
    if "base_id" in body and body["base_id"] is not None:
        must_exist(db.bases, body["base_id"], "Base")
    rec = stamp_new({
        "base_id": v_str(body, "base_id"),
        "tail_number": v_str(body, "tail_number"),
        "aircraft_class": v_enum(body, "aircraft_class", AIRCRAFT_CLASSES),
        "medical_config": v_enum(body, "medical_config", MEDICAL_CONFIGS),
        "status": "AVAILABLE",
    })
    db.aircraft[rec["id"]] = rec
    return ok_object(ser_aircraft(rec), 201)


@bp.route("/air-ambulance/aircraft/<rid>", methods=["GET"])
def get_aircraft(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.aircraft, rid, "Aircraft")
    return ok_object(ser_aircraft(rec))


@bp.route("/air-ambulance/aircraft", methods=["GET"])
def list_aircraft():
    require_roles(*ALL_ROLES)
    return list_response(
        db.aircraft.values(), ser_aircraft,
        {"base_id": "base_id", "status": "status"},
    )


@bp.route("/air-ambulance/aircraft/<rid>", methods=["PUT"])
def update_aircraft(rid):
    require_roles("OpsAdmin")
    rec = must_exist(db.aircraft, rid, "Aircraft")
    body = get_body()
    target = v_enum(body, "status", AIRCRAFT_STATUSES)
    # Manual control spans MAINTENANCE <-> AVAILABLE only; ASSIGNED is
    # system-owned and rejects any manual write with ERR_INVALID_STATE.
    if rec["status"] == "ASSIGNED" or target == "ASSIGNED":
        fail(ERR_INVALID_STATE, 409,
             "Aircraft status %s cannot be manually set to %s" % (rec["status"], target))
    rec["status"] = target
    touch(rec)
    return ok_object(ser_aircraft(rec))


# ---------------------------------------------------------------------------
# Crew members
# ---------------------------------------------------------------------------


@bp.route("/air-ambulance/crew-members", methods=["POST"])
def create_crew_member():
    require_roles("OpsAdmin")
    body = get_body()
    if "base_id" in body and body["base_id"] is not None:
        must_exist(db.bases, body["base_id"], "Base")
    rec = stamp_new({
        "base_id": v_str(body, "base_id"),
        "full_name": v_str(body, "full_name"),
        "crew_role": v_enum(body, "crew_role", CREW_ROLES),
        "status": "ACTIVE",
    })
    db.crew_members[rec["id"]] = rec
    return ok_object(ser_crew_member(rec), 201)


@bp.route("/air-ambulance/crew-members/<rid>", methods=["GET"])
def get_crew_member(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.crew_members, rid, "CrewMember")
    return ok_object(ser_crew_member(rec))


@bp.route("/air-ambulance/crew-members", methods=["GET"])
def list_crew_members():
    require_roles(*ALL_ROLES)
    return list_response(
        db.crew_members.values(), ser_crew_member,
        {"base_id": "base_id", "status": "status", "crew_role": "crew_role"},
    )


@bp.route("/air-ambulance/crew-members/<rid>", methods=["PUT"])
def update_crew_member(rid):
    require_roles("OpsAdmin")
    rec = must_exist(db.crew_members, rid, "CrewMember")
    body = get_body()
    target = v_enum(body, "status", CREW_STATUSES)
    # REMEDIATION_HOLD is reachable only via the QA cascade, never by command.
    valid = (
        (rec["status"] == "REMEDIATION_HOLD" and target == "ACTIVE")
        or (rec["status"] == "ACTIVE" and target == "INACTIVE")
        or (rec["status"] == "INACTIVE" and target == "ACTIVE")
    )
    if not valid:
        fail(ERR_INVALID_STATE, 409,
             "CrewMember status %s cannot transition to %s" % (rec["status"], target))
    rec["status"] = target
    touch(rec)
    return ok_object(ser_crew_member(rec))


# ---------------------------------------------------------------------------
# Crew shifts (C5 fatigue gates; order: duty projection -> rest -> overlap)
# ---------------------------------------------------------------------------


@bp.route("/air-ambulance/crew-shifts", methods=["POST"])
def create_crew_shift():
    user_id, role = require_roles("OpsAdmin", "FlightCrew")
    body = get_body()
    # FlightCrew ownership (priority 2) precedes body-FK existence (priority 3)
    if role == "FlightCrew":
        if body.get("crew_member_id") is not None and body.get("crew_member_id") != user_id:
            fail(ERR_FORBIDDEN, 403, "FlightCrew callers may only plan their own shifts")
    if "crew_member_id" in body and body["crew_member_id"] is not None:
        must_exist(db.crew_members, body["crew_member_id"], "CrewMember")
    member_id = v_str(body, "crew_member_id")
    start_raw, start = v_dt(body, "planned_start_iso")
    end_raw, end = v_dt(body, "planned_end_iso")
    if not (end > start):
        fail(ERR_VALIDATION, 400, "planned_end_iso must be strictly after planned_start_iso")
    planned_minutes = int((end - start).total_seconds() // 60)
    # C5 gates in the PRD's stated reporting order: duty, rest, overlap
    if calc.duty_projection_exceeded(member_id, start, end, planned_minutes):
        fail(ERR_DUTY_LIMIT_EXCEEDED, 422,
             "Projected rolling-24h duty minutes exceed 840")
    if calc.insufficient_rest(member_id, start):
        fail(ERR_INSUFFICIENT_REST, 422,
             "Less than 600 minutes rest since the member's latest prior shift end")
    if calc.shift_overlaps(member_id, start, end):
        fail(ERR_SHIFT_OVERLAP, 409,
             "Candidate shift overlaps an existing shift of the member")
    rec = stamp_new({
        "crew_member_id": member_id,
        "planned_start_iso": start_raw,
        "planned_end_iso": end_raw,
        "actual_end_iso": None,
        "planned_minutes": planned_minutes,
        "status": "OPEN",
        "_planned_start": start,
        "_planned_end": end,
        "_actual_end": None,
    })
    db.crew_shifts[rec["id"]] = rec
    return ok_object(ser_crew_shift(rec), 201)


@bp.route("/air-ambulance/crew-shifts/<rid>", methods=["GET"])
def get_crew_shift(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.crew_shifts, rid, "CrewShift")
    return ok_object(ser_crew_shift(rec))


@bp.route("/air-ambulance/crew-shifts", methods=["GET"])
def list_crew_shifts():
    require_roles(*ALL_ROLES)
    return list_response(
        db.crew_shifts.values(), ser_crew_shift,
        {"crew_member_id": "crew_member_id", "status": "status"},
    )


@bp.route("/air-ambulance/crew-shifts/<rid>", methods=["PUT"])
def update_crew_shift(rid):
    user_id, role = require_roles("OpsAdmin", "FlightCrew")
    rec = must_exist(db.crew_shifts, rid, "CrewShift")
    if role == "FlightCrew" and rec["crew_member_id"] != user_id:
        fail(ERR_FORBIDDEN, 403, "FlightCrew callers may only close their own shifts")
    body = get_body()
    target = v_enum(body, "status", SHIFT_STATUSES)
    if rec["status"] != "OPEN" or target != "CLOSED":
        fail(ERR_INVALID_STATE, 409,
             "CrewShift status %s cannot transition to %s" % (rec["status"], target))
    rec["status"] = "CLOSED"
    rec["actual_end_iso"] = now_iso()
    rec["_actual_end"] = db.clock
    touch(rec)
    return ok_object(ser_crew_shift(rec))


# ---------------------------------------------------------------------------
# Test-driving logical clock (OpsAdmin)
# ---------------------------------------------------------------------------


@bp.route("/air-ambulance/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("OpsAdmin")
    body = get_body()
    raw = v_str(body, "to_iso8601")
    parsed = parse_dt(raw)
    if parsed is None:
        fail(ERR_VALIDATION, 400, "to_iso8601 must be an ISO 8601 datetime")
    db.clock = parsed
    return ok_object({"current_utc": render_ts(db.clock)})
