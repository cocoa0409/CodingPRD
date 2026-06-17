"""Vehicle Safety & Emissions Inspection API — Flask entry point.

Single-file route registration. Storage is in-memory (db.py); no seeding at boot.
Validation order per PRD §2.9: auth -> RBAC -> existence -> body well-formedness
-> state -> OCC -> business rules.
"""
import os
from datetime import timedelta

from flask import Flask, request

import db
import calculations as calc
from errors import ApiError, err
from middleware import authenticate, authorize
from response import object_response, array_response, error_response
from serialize import serialize, serialize_list
from validation import (
    get_json_body, require, opt, require_str, opt_str, require_bool, opt_bool,
    require_int, opt_int, require_enum, opt_enum, require_vin, require_state_code,
    require_datetime, parse_datetime, parse_pagination,
)

app = Flask(__name__)

# ----- Enumerations (PRD §2.10) -----
VEHICLE_CLASSES = {"PASSENGER", "LIGHT_TRUCK", "HEAVY_DUTY", "MOTORCYCLE"}
APPT_KINDS = {"APPOINTMENT", "WALK_IN"}
CHECKLIST_OUTCOMES = {"PASS", "FAIL", "NA"}
SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
PROTOCOLS = {"OBD2_CAN", "OBD2_ISO", "OBD2_J1850"}
COST_BASES = {"DOCUMENTED_ONLY", "DOCUMENTED_PLUS_ESTIMATED"}


# ============================================================================
# Error handling
# ============================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e), 422)


# ============================================================================
# Shared helpers
# ============================================================================
def lookup(store, rid):
    """Existence check (PRD §2.6). Raises ERR_NOT_FOUND when unresolved."""
    if rid is None or rid not in store:
        raise err("ERR_NOT_FOUND", "Referenced resource does not exist.")
    return store[rid]


def list_and_paginate(records, predicate=None):
    """Filter, sort by created order (created_at ASC, PRD §2.3), paginate."""
    limit, offset = parse_pagination()
    items = list(records)
    if predicate is not None:
        items = [r for r in items if predicate(r)]
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return serialize_list(page), limit, offset, total


# Reinspection chain helpers
def chain_head(record):
    """Return the head record of this record's reinspection chain."""
    head_id = record.get("original_record_id")
    if head_id is None:
        return record
    return db.inspection_records.get(head_id, record)


def profile_for(station_id, vehicle_class):
    for p in db.vehicle_class_profiles.values():
        if p["station_id"] == station_id and p["vehicle_class"] == vehicle_class:
            return p
    return None


# ============================================================================
# Logical clock (PRD §2.11)
# ============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    _, role = authenticate()
    authorize(role, {"StationManager"})
    body = get_json_body()
    iso = require(body, "to_iso8601")
    dt = parse_datetime(iso, "to_iso8601")
    db.set_clock(dt)
    return object_response({}, 200)


# ============================================================================
# Station (PRD §3.1)
# ============================================================================
@app.route("/stations", methods=["POST"])
def create_station():
    _, role = authenticate()
    authorize(role, {"StationManager"})
    body = get_json_body()
    name = require_str(body, "name")
    state_code = require_state_code(body, "state_code")
    prefix = require_str(body, "certificate_serial_prefix")
    repair_limit = require_int(body, "repair_cost_limit_cents", min_value=1)
    analyzer_count = opt_int(body, "analyzer_count", default=1, min_value=1)
    rec = {
        "name": name,
        "state_code": state_code,
        "certificate_serial_prefix": prefix,
        "next_certificate_seq": 1,
        "repair_cost_limit_cents": repair_limit,
        "analyzer_count": analyzer_count,
    }
    db.stamp_create(rec)
    db.stations[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/stations/<rid>", methods=["GET"])
def get_station(rid):
    _, role = authenticate()
    authorize(role, {"StationManager", "Inspector", "Receptionist", "StateAuditor"})
    rec = lookup(db.stations, rid)
    return object_response(serialize(rec), 200)


# ============================================================================
# VehicleClassProfile (PRD §3.1)
# ============================================================================
@app.route("/vehicle-class-profiles", methods=["POST"])
def create_profile():
    _, role = authenticate()
    authorize(role, {"StationManager"})
    body = get_json_body()
    station_id = require_str(body, "station_id")
    lookup(db.stations, station_id)
    vehicle_class = require_enum(body, "vehicle_class", VEHICLE_CLASSES)
    base_fee = require_int(body, "base_fee_cents", min_value=1)
    obd_required = require_bool(body, "obd_required")
    item_count = require_int(body, "checklist_item_count", min_value=1)
    window_days = opt_int(body, "reinspection_window_days", default=30, min_value=0)
    rec = {
        "station_id": station_id,
        "vehicle_class": vehicle_class,
        "base_fee_cents": base_fee,
        "obd_required": obd_required,
        "checklist_item_count": item_count,
        "reinspection_window_days": window_days,
    }
    db.stamp_create(rec)
    db.vehicle_class_profiles[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/vehicle-class-profiles/<rid>", methods=["GET"])
def get_profile(rid):
    _, role = authenticate()
    authorize(role, {"StationManager", "Inspector", "Receptionist"})
    rec = lookup(db.vehicle_class_profiles, rid)
    return object_response(serialize(rec), 200)


@app.route("/vehicle-class-profiles", methods=["GET"])
def list_profiles():
    _, role = authenticate()
    authorize(role, {"StationManager", "Inspector", "Receptionist"})
    station_id = request.args.get("station_id")
    vehicle_class = request.args.get("vehicle_class")

    def pred(r):
        if station_id is not None and r["station_id"] != station_id:
            return False
        if vehicle_class is not None and r["vehicle_class"] != vehicle_class:
            return False
        return True

    items, limit, offset, total = list_and_paginate(db.vehicle_class_profiles.values(), pred)
    return array_response(items, limit, offset, total, 200)


# ============================================================================
# Lane (PRD §3.1)
# ============================================================================
@app.route("/lanes", methods=["POST"])
def create_lane():
    _, role = authenticate()
    authorize(role, {"StationManager"})
    body = get_json_body()
    station_id = require_str(body, "station_id")
    lookup(db.stations, station_id)
    lane_number = require_int(body, "lane_number", min_value=1)
    supports_obd = require_bool(body, "supports_obd")
    buffer_minutes = opt_int(body, "turnaround_buffer_minutes", default=0, min_value=0)
    rec = {
        "station_id": station_id,
        "lane_number": lane_number,
        "supports_obd": supports_obd,
        "turnaround_buffer_minutes": buffer_minutes,
    }
    db.stamp_create(rec)
    db.lanes[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/lanes/<rid>", methods=["GET"])
def get_lane(rid):
    _, role = authenticate()
    authorize(role, {"StationManager", "Inspector", "Receptionist"})
    rec = lookup(db.lanes, rid)
    return object_response(serialize(rec), 200)


@app.route("/lanes", methods=["GET"])
def list_lanes():
    _, role = authenticate()
    authorize(role, {"StationManager", "Inspector", "Receptionist"})
    station_id = request.args.get("station_id")

    def pred(r):
        return station_id is None or r["station_id"] == station_id

    items, limit, offset, total = list_and_paginate(db.lanes.values(), pred)
    return array_response(items, limit, offset, total, 200)


@app.route("/lanes/<rid>/appointments", methods=["GET"])
def list_lane_appointments(rid):
    _, role = authenticate()
    authorize(role, {"StationManager", "Inspector", "Receptionist"})
    lookup(db.lanes, rid)
    items, limit, offset, total = list_and_paginate(
        db.appointments.values(), lambda a: a["lane_id"] == rid)
    return array_response(items, limit, offset, total, 200)


# ============================================================================
# AnalyzerReservation (PRD §3.3)
# ============================================================================
def _intervals_strictly_overlap(s1, e1, s2, e2):
    """Half-open [s, e) positive-length intersection (PRD §3.3)."""
    return s1 < e2 and s2 < e1


@app.route("/analyzer-reservations", methods=["POST"])
def create_analyzer_reservation():
    _, role = authenticate()
    authorize(role, {"Receptionist", "StationManager"})
    body = get_json_body()
    station_id = require_str(body, "station_id")
    station = lookup(db.stations, station_id)
    vin = require_vin(body, "vehicle_vin")
    window_start = require_datetime(body, "window_start")
    window_end = require_datetime(body, "window_end")
    # window_end must be strictly after window_start (constraint -> ERR_INVALID_REQUEST).
    if not (window_end > window_start):
        raise err("ERR_INVALID_REQUEST", "window_end must be strictly after window_start.")

    # Aggregate-capacity overlap (PRD §3.3, validation priority 9).
    overlapping = 0
    for r in db.analyzer_reservations.values():
        if r["station_id"] != station_id or r["status"] != "HELD":
            continue
        rs = calc._parse_iso(r["window_start"])
        re_ = calc._parse_iso(r["window_end"])
        if _intervals_strictly_overlap(window_start, window_end, rs, re_):
            overlapping += 1
    # Admitting it would make the count of mutually overlapping held windows
    # = overlapping + 1; rejected if that reaches analyzer_count or beyond.
    if overlapping + 1 > station["analyzer_count"]:
        raise err("ERR_ANALYZER_CAPACITY", "Analyzer capacity exceeded for the requested window.")

    rec = {
        "station_id": station_id,
        "vehicle_vin": vin,
        "window_start": _iso(window_start),
        "window_end": _iso(window_end),
        "status": "HELD",
    }
    db.stamp_create(rec)
    db.analyzer_reservations[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/analyzer-reservations/<rid>", methods=["GET"])
def get_analyzer_reservation(rid):
    _, role = authenticate()
    authorize(role, {"Receptionist", "StationManager", "Inspector"})
    rec = lookup(db.analyzer_reservations, rid)
    return object_response(serialize(rec), 200)


@app.route("/analyzer-reservations", methods=["GET"])
def list_analyzer_reservations():
    _, role = authenticate()
    authorize(role, {"Receptionist", "StationManager", "Inspector"})
    station_id = request.args.get("station_id")
    status = request.args.get("status")

    def pred(r):
        if station_id is not None and r["station_id"] != station_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    items, limit, offset, total = list_and_paginate(db.analyzer_reservations.values(), pred)
    return array_response(items, limit, offset, total, 200)


@app.route("/analyzer-reservations/<rid>/release", methods=["POST"])
def release_analyzer_reservation(rid):
    _, role = authenticate()
    authorize(role, {"Receptionist", "StationManager"})
    rec = lookup(db.analyzer_reservations, rid)
    if rec["status"] != "HELD":
        raise err("ERR_INVALID_STATE", "Reservation is not HELD.")
    rec["status"] = "RELEASED"
    db.touch(rec)
    return object_response(serialize(rec), 200)


# ============================================================================
# Appointment (PRD §3.2)
# ============================================================================
@app.route("/appointments", methods=["POST"])
def create_appointment():
    _, role = authenticate()
    authorize(role, {"Receptionist", "StationManager"})
    body = get_json_body()
    lane_id = require_str(body, "lane_id")
    lane = lookup(db.lanes, lane_id)
    vin = require_vin(body, "vehicle_vin")
    vehicle_class = require_enum(body, "vehicle_class", VEHICLE_CLASSES)
    kind = require_enum(body, "kind", APPT_KINDS)
    scheduled_start = require_datetime(body, "scheduled_start")
    scheduled_end = require_datetime(body, "scheduled_end")

    # Priority 7: valid interval.
    if not (scheduled_end > scheduled_start):
        raise err("ERR_INVALID_TIME_RANGE", "scheduled_end must be strictly after scheduled_start.")

    # Priority 8: lane time conflict (buffered, half-open). New span:
    # [start, end + buffer); compared against existing [start, end + buffer)
    # of non-released appointments on the same lane.
    buffer_min = lane["turnaround_buffer_minutes"]
    new_start = scheduled_start
    new_end = scheduled_end + timedelta(minutes=buffer_min)
    for a in db.appointments.values():
        if a["lane_id"] != lane_id:
            continue
        if a["status"] not in ("BOOKED", "CHECKED_IN", "CONSUMED"):
            continue
        ex_start = calc._parse_iso(a["scheduled_start"])
        ex_end = calc._parse_iso(a["scheduled_end"]) + timedelta(minutes=buffer_min)
        if _intervals_strictly_overlap(new_start, new_end, ex_start, ex_end):
            raise err("ERR_LANE_TIME_CONFLICT", "Requested slot overlaps an existing appointment on this lane.")

    # Priority 10: class profile must exist at the lane's station.
    if profile_for(lane["station_id"], vehicle_class) is None:
        raise err("ERR_CLASS_PROFILE_MISSING", "No vehicle-class profile for this class at the lane's station.")

    rec = {
        "lane_id": lane_id,
        "vehicle_vin": vin,
        "vehicle_class": vehicle_class,
        "kind": kind,
        "scheduled_start": _iso(scheduled_start),
        "scheduled_end": _iso(scheduled_end),
        "status": "BOOKED",
    }
    db.stamp_create(rec)
    db.appointments[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/appointments/<rid>", methods=["GET"])
def get_appointment(rid):
    _, role = authenticate()
    authorize(role, {"Receptionist", "StationManager", "Inspector"})
    rec = lookup(db.appointments, rid)
    return object_response(serialize(rec), 200)


@app.route("/appointments/<rid>/check-in", methods=["POST"])
def checkin_appointment(rid):
    _, role = authenticate()
    authorize(role, {"Receptionist", "StationManager"})
    rec = lookup(db.appointments, rid)
    if rec["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Appointment is not BOOKED.")
    rec["status"] = "CHECKED_IN"
    db.touch(rec)
    return object_response(serialize(rec), 200)


@app.route("/appointments/<rid>/cancel", methods=["POST"])
def cancel_appointment(rid):
    _, role = authenticate()
    authorize(role, {"Receptionist", "StationManager"})
    rec = lookup(db.appointments, rid)
    if rec["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Appointment is not BOOKED.")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return object_response(serialize(rec), 200)


@app.route("/appointments/<rid>/no-show", methods=["POST"])
def noshow_appointment(rid):
    _, role = authenticate()
    authorize(role, {"Receptionist", "StationManager"})
    rec = lookup(db.appointments, rid)
    if rec["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Appointment is not BOOKED.")
    clock = db.current_clock()
    sched_end = calc._parse_iso(rec["scheduled_end"])
    if clock is None or clock < sched_end:
        raise err("ERR_INVALID_STATE", "Cannot mark no-show before scheduled_end.")
    rec["status"] = "NO_SHOW"
    db.touch(rec)
    return object_response(serialize(rec), 200)


# ============================================================================
# InspectionRecord (PRD §3.4, §3.5, §3.9)
# ============================================================================
@app.route("/inspection-records", methods=["POST"])
def create_inspection_record():
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager"})
    body = get_json_body()
    appointment_id = require_str(body, "appointment_id")
    appt = lookup(db.appointments, appointment_id)
    original_record_id = opt_str(body, "original_record_id", default=None)
    original = None
    if original_record_id is not None:
        original = lookup(db.inspection_records, original_record_id)

    # State: appointment must be CHECKED_IN, and no non-ABORTED record may
    # already reference this appointment (PRD §3.4 -> ERR_INVALID_STATE).
    if appt["status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Appointment is not CHECKED_IN.")
    for r in db.inspection_records.values():
        if r["appointment_id"] == appointment_id and r["status"] != "ABORTED":
            raise err("ERR_INVALID_STATE", "A non-aborted record already references this appointment.")

    lane = db.lanes.get(appt["lane_id"])
    station_id = lane["station_id"] if lane else None

    reinspection_index = 0
    head_id = None
    if original is not None:
        head = chain_head(original)
        head_id = head["id"]
        reinspection_index = head["reinspection_index"] + 1

    rec = {
        "appointment_id": appointment_id,
        "station_id": station_id,
        "vehicle_vin": appt["vehicle_vin"],
        "vehicle_class": appt["vehicle_class"],
        "original_record_id": head_id,
        "reinspection_index": reinspection_index,
        "status": "IN_PROGRESS",
        "safety_result": "PENDING",
        "emissions_result": "PENDING",
        "fee_cents": 0,
        "waiver_applied": False,
    }
    db.stamp_create(rec)
    db.inspection_records[rec["id"]] = rec

    # Consume the appointment (CHECKED_IN -> CONSUMED).
    appt["status"] = "CONSUMED"
    db.touch(appt)

    return object_response(serialize(rec), 201)


@app.route("/inspection-records/<rid>", methods=["GET"])
def get_inspection_record(rid):
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager", "Receptionist", "StateAuditor"})
    rec = lookup(db.inspection_records, rid)
    return object_response(serialize(rec), 200)


@app.route("/inspection-records", methods=["GET"])
def list_inspection_records():
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager", "StateAuditor"})
    appointment_id = request.args.get("appointment_id")
    original_record_id = request.args.get("original_record_id")
    station_id = request.args.get("station_id")
    status = request.args.get("status")

    def pred(r):
        if appointment_id is not None and r["appointment_id"] != appointment_id:
            return False
        if original_record_id is not None and r["original_record_id"] != original_record_id:
            return False
        if station_id is not None and r["station_id"] != station_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    items, limit, offset, total = list_and_paginate(db.inspection_records.values(), pred)
    return array_response(items, limit, offset, total, 200)


def _has_approved_waiver(record_id):
    for w in db.waiver_requests.values():
        if w["record_id"] == record_id and w["status"] == "APPROVED":
            return True
    return False


def _emissions_test_for(record_id):
    tests = [t for t in db.emissions_tests.values() if t["record_id"] == record_id]
    return tests[0] if tests else None


@app.route("/inspection-records/<rid>/decide", methods=["POST"])
def decide_inspection_record(rid):
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager"})
    rec = lookup(db.inspection_records, rid)
    # State: must be IN_PROGRESS.
    if rec["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Record is not IN_PROGRESS.")

    profile = profile_for(rec["station_id"], rec["vehicle_class"])
    if profile is None:
        # Configuration gap; treated as incomplete (cannot evaluate).
        raise err("ERR_INSPECTION_INCOMPLETE", "No class profile for the record.")

    # Completeness (priority 12): checklist count must equal item_count, and
    # if obd_required exactly one EmissionsTest must exist.
    checklist_rows = [c for c in db.checklist_results.values() if c["record_id"] == rid]
    if len(checklist_rows) != profile["checklist_item_count"]:
        raise err("ERR_INSPECTION_INCOMPLETE", "Checklist is incomplete.")
    emissions_test = _emissions_test_for(rid)
    if profile["obd_required"]:
        if emissions_test is None:
            raise err("ERR_INSPECTION_INCOMPLETE", "Required emissions test is missing.")

    # Compute component results.
    safety_result = calc.evaluate_safety_result(rid)
    if profile["obd_required"]:
        emissions_result = calc.evaluate_obd_result(emissions_test)
        # Re-affirm onto the test row.
        if emissions_test["result"] != emissions_result:
            emissions_test["result"] = emissions_result
            db.touch(emissions_test)
    else:
        emissions_result = "NOT_APPLICABLE"

    rec["safety_result"] = safety_result
    rec["emissions_result"] = emissions_result

    approved_waiver = _has_approved_waiver(rid)

    # Determine PASS vs FAIL (PRD §3.5).
    passes = True
    if safety_result != "PASS":
        passes = False
    if profile["obd_required"]:
        if not (emissions_result == "PASS" or approved_waiver):
            passes = False

    head = chain_head(rec)
    rec["fee_cents"] = calc.compute_inspection_fee(rec, profile, head)

    if passes:
        rec["status"] = "PASSED"
        rec["waiver_applied"] = (emissions_result == "FAIL" and approved_waiver)
    else:
        rec["status"] = "FAILED"
        rec["waiver_applied"] = False

    db.touch(rec)
    return object_response(serialize(rec), 200)


@app.route("/inspection-records/<rid>/reinspect", methods=["POST"])
def reinspect_inspection_record(rid):
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager"})
    rec = lookup(db.inspection_records, rid)
    body = get_json_body()
    appt_id = require_str(body, "reinspection_appointment_id")
    appt = lookup(db.appointments, appt_id)

    # State: source must be FAILED or PASSED.
    if rec["status"] not in ("FAILED", "PASSED"):
        raise err("ERR_INVALID_STATE", "Reinspection requires a FAILED or PASSED record.")
    # Supplied appointment must be CHECKED_IN.
    if appt["status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Reinspection appointment is not CHECKED_IN.")
    # Reinspection ceiling (priority 16): allowed only while index < 3.
    if rec["reinspection_index"] >= 3:
        raise err("ERR_REINSPECTION_LIMIT", "Reinspection chain at its ceiling.")

    head = chain_head(rec)
    was_passed = (rec["status"] == "PASSED")

    # LINK 1: supersede the chain-head/source record (bump version, keep status).
    db.touch(rec)

    # LINK 2 + 3: if the source is a PASSED record holding an ACTIVE certificate,
    # cascade Certificate ACTIVE -> VOID -> sticker revoke (PRD §3.9).
    if was_passed:
        for cert in db.certificates.values():
            if cert["record_id"] == rec["id"] and cert["status"] == "ACTIVE":
                cert["status"] = "VOID"
                cert["sticker_number"] = None  # revoked / surrendered
                db.touch(cert)

    # Create the new IN_PROGRESS record.
    lane = db.lanes.get(appt["lane_id"])
    station_id = lane["station_id"] if lane else None
    new_rec = {
        "appointment_id": appt_id,
        "station_id": station_id,
        "vehicle_vin": appt["vehicle_vin"],
        "vehicle_class": appt["vehicle_class"],
        "original_record_id": head["id"],
        "reinspection_index": rec["reinspection_index"] + 1,
        "status": "IN_PROGRESS",
        "safety_result": "PENDING",
        "emissions_result": "PENDING",
        "fee_cents": 0,
        "waiver_applied": False,
    }
    db.stamp_create(new_rec)
    db.inspection_records[new_rec["id"]] = new_rec

    # Consume the supplied appointment.
    appt["status"] = "CONSUMED"
    db.touch(appt)

    return object_response(serialize(new_rec), 201)


@app.route("/inspection-records/<rid>/abort", methods=["POST"])
def abort_inspection_record(rid):
    _, role = authenticate()
    authorize(role, {"StationManager"})
    rec = lookup(db.inspection_records, rid)
    if rec["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Record is not IN_PROGRESS.")
    rec["status"] = "ABORTED"
    db.touch(rec)
    return object_response(serialize(rec), 200)


@app.route("/inspection-records/<rid>/waiver-eligibility", methods=["GET"])
def waiver_eligibility(rid):
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager"})
    rec = lookup(db.inspection_records, rid)
    station = db.stations.get(rec["station_id"])
    limit_cents = station["repair_cost_limit_cents"] if station else 0
    doc = calc.compute_qualifying_repair_spend(rid, "DOCUMENTED_ONLY")
    doc_plus = calc.compute_qualifying_repair_spend(rid, "DOCUMENTED_PLUS_ESTIMATED")
    data = {
        "documented_only_spend_cents": doc,
        "documented_plus_estimated_spend_cents": doc_plus,
        "repair_cost_limit_cents": limit_cents,
        "eligible_documented_only": doc >= limit_cents,
        "eligible_documented_plus_estimated": doc_plus >= limit_cents,
    }
    return object_response(data, 200)


@app.route("/inspection-records/<rid>/state-surcharge", methods=["GET"])
def state_surcharge_preview(rid):
    _, role = authenticate()
    authorize(role, {"StationManager", "StateAuditor"})
    rec = lookup(db.inspection_records, rid)
    service_portion, surcharge = calc.compute_state_surcharge_for_fee(rec["fee_cents"])
    data = {
        "service_portion_cents": service_portion,
        "state_surcharge_cents": surcharge,
    }
    return object_response(data, 200)


# ============================================================================
# ChecklistResult (PRD §3.4)
# ============================================================================
@app.route("/checklist-results", methods=["POST"])
def create_checklist_result():
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager"})
    body = get_json_body()
    record_id = require_str(body, "record_id")
    record = lookup(db.inspection_records, record_id)
    item_code = require_str(body, "item_code")
    outcome = require_enum(body, "outcome", CHECKLIST_OUTCOMES)
    severity = opt_enum(body, "severity", SEVERITIES, default="MINOR")
    # Record must be IN_PROGRESS (PRD §3.4: "While the record is IN_PROGRESS").
    if record["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Record is not IN_PROGRESS.")
    rec = {
        "record_id": record_id,
        "item_code": item_code,
        "outcome": outcome,
        "severity": severity,
    }
    db.stamp_create(rec)
    db.checklist_results[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/checklist-results/<rid>", methods=["GET"])
def get_checklist_result(rid):
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager", "StateAuditor"})
    rec = lookup(db.checklist_results, rid)
    return object_response(serialize(rec), 200)


@app.route("/checklist-results", methods=["GET"])
def list_checklist_results():
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager", "StateAuditor"})
    record_id = request.args.get("record_id")

    def pred(r):
        return record_id is None or r["record_id"] == record_id

    items, limit, offset, total = list_and_paginate(db.checklist_results.values(), pred)
    return array_response(items, limit, offset, total, 200)


# ============================================================================
# EmissionsTest (PRD §3.4)
# ============================================================================
@app.route("/emissions-tests", methods=["POST"])
def create_emissions_test():
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager"})
    body = get_json_body()
    record_id = require_str(body, "record_id")
    record = lookup(db.inspection_records, record_id)
    protocol = require_enum(body, "protocol", PROTOCOLS)
    dtc_count = require_int(body, "dtc_count", min_value=0)
    monitors = require_int(body, "readiness_monitors_incomplete", min_value=0)
    mil_on = require_bool(body, "mil_on")

    # Record must be IN_PROGRESS (PRD §3.4 — attached while in progress).
    if record["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Record is not IN_PROGRESS.")

    profile = profile_for(record["station_id"], record["vehicle_class"])
    # OBD applicability + at-most-one (priority 11 -> ERR_OBD_NOT_APPLICABLE).
    if profile is None or not profile["obd_required"]:
        raise err("ERR_OBD_NOT_APPLICABLE", "Class does not require OBD.")
    if _emissions_test_for(record_id) is not None:
        raise err("ERR_OBD_NOT_APPLICABLE", "An emissions test already exists for this record.")

    rec = {
        "record_id": record_id,
        "protocol": protocol,
        "dtc_count": dtc_count,
        "readiness_monitors_incomplete": monitors,
        "mil_on": mil_on,
        "result": "PENDING",
    }
    rec["result"] = calc.evaluate_obd_result(rec)
    db.stamp_create(rec)
    db.emissions_tests[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/emissions-tests/<rid>", methods=["GET"])
def get_emissions_test(rid):
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager", "StateAuditor"})
    rec = lookup(db.emissions_tests, rid)
    return object_response(serialize(rec), 200)


@app.route("/emissions-tests", methods=["GET"])
def list_emissions_tests():
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager", "StateAuditor"})
    record_id = request.args.get("record_id")

    def pred(r):
        return record_id is None or r["record_id"] == record_id

    items, limit, offset, total = list_and_paginate(db.emissions_tests.values(), pred)
    return array_response(items, limit, offset, total, 200)


# ============================================================================
# RepairOrder (PRD §3.7)
# ============================================================================
@app.route("/repair-orders", methods=["POST"])
def create_repair_order():
    _, role = authenticate()
    authorize(role, {"Receptionist", "StationManager"})
    body = get_json_body()
    record_id = require_str(body, "record_id")
    lookup(db.inspection_records, record_id)
    shop_name = require_str(body, "shop_name")
    documented = opt_int(body, "documented_cost_cents", default=0, min_value=0)
    estimated = opt_int(body, "estimated_cost_cents", default=0, min_value=0)
    emissions_related = require_bool(body, "emissions_related")
    rec = {
        "record_id": record_id,
        "shop_name": shop_name,
        "documented_cost_cents": documented,
        "estimated_cost_cents": estimated,
        "emissions_related": emissions_related,
        "status": "SUBMITTED",
    }
    db.stamp_create(rec)
    db.repair_orders[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/repair-orders/<rid>", methods=["GET"])
def get_repair_order(rid):
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager", "StateAuditor"})
    rec = lookup(db.repair_orders, rid)
    return object_response(serialize(rec), 200)


@app.route("/repair-orders", methods=["GET"])
def list_repair_orders():
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager", "StateAuditor"})
    record_id = request.args.get("record_id")
    status = request.args.get("status")

    def pred(r):
        if record_id is not None and r["record_id"] != record_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    items, limit, offset, total = list_and_paginate(db.repair_orders.values(), pred)
    return array_response(items, limit, offset, total, 200)


@app.route("/repair-orders/<rid>/verify", methods=["POST"])
def verify_repair_order(rid):
    _, role = authenticate()
    authorize(role, {"StationManager"})
    rec = lookup(db.repair_orders, rid)
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Repair order is not SUBMITTED.")
    record = db.inspection_records.get(rec["record_id"])
    # Verify gate (PRD §3.7): referenced record FAILED with emissions_result FAIL.
    if record is None or record["status"] != "FAILED" or record["emissions_result"] != "FAIL":
        raise err("ERR_INVALID_STATE", "Referenced record is not FAILED with emissions FAIL.")
    rec["status"] = "VERIFIED"
    db.touch(rec)
    return object_response(serialize(rec), 200)


@app.route("/repair-orders/<rid>/reject", methods=["POST"])
def reject_repair_order(rid):
    _, role = authenticate()
    authorize(role, {"StationManager"})
    rec = lookup(db.repair_orders, rid)
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Repair order is not SUBMITTED.")
    rec["status"] = "REJECTED"
    db.touch(rec)
    return object_response(serialize(rec), 200)


# ============================================================================
# WaiverRequest (PRD §3.8)
# ============================================================================
@app.route("/waiver-requests", methods=["POST"])
def create_waiver_request():
    _, role = authenticate()
    authorize(role, {"Receptionist", "StationManager"})
    body = get_json_body()
    record_id = require_str(body, "record_id")
    lookup(db.inspection_records, record_id)
    cost_basis = require_enum(body, "cost_basis", COST_BASES)
    rec = {
        "record_id": record_id,
        "cost_basis": cost_basis,
        "qualifying_spend_cents": 0,
        "status": "REQUESTED",
    }
    db.stamp_create(rec)
    db.waiver_requests[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/waiver-requests/<rid>", methods=["GET"])
def get_waiver_request(rid):
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager", "StateAuditor"})
    rec = lookup(db.waiver_requests, rid)
    return object_response(serialize(rec), 200)


@app.route("/waiver-requests", methods=["GET"])
def list_waiver_requests():
    _, role = authenticate()
    authorize(role, {"Inspector", "StationManager", "StateAuditor"})
    record_id = request.args.get("record_id")
    status = request.args.get("status")

    def pred(r):
        if record_id is not None and r["record_id"] != record_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    items, limit, offset, total = list_and_paginate(db.waiver_requests.values(), pred)
    return array_response(items, limit, offset, total, 200)


@app.route("/waiver-requests/<rid>/decide", methods=["POST"])
def decide_waiver_request(rid):
    _, role = authenticate()
    authorize(role, {"StationManager"})
    rec = lookup(db.waiver_requests, rid)
    body = get_json_body()
    decision = require(body, "decision")
    if not isinstance(decision, str):
        raise err("ERR_INVALID_REQUEST", "decision must be a string.")
    decision_upper = decision.upper()
    if decision_upper not in ("APPROVE", "DENY"):
        raise err("ERR_INVALID_REQUEST", "decision must be APPROVE or DENY.")
    # State: must be REQUESTED.
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Waiver request is not REQUESTED.")

    record = db.inspection_records.get(rec["record_id"])
    spend = calc.compute_qualifying_repair_spend(rec["record_id"], rec["cost_basis"])

    if decision_upper == "APPROVE":
        # Approval gate (PRD §3.8): record FAILED with emissions FAIL, and
        # spend >= station repair_cost_limit_cents.
        station = db.stations.get(record["station_id"]) if record else None
        if record is None or record["status"] != "FAILED" or record["emissions_result"] != "FAIL":
            raise err("ERR_INVALID_STATE", "Record is not FAILED with emissions FAIL.")
        limit_cents = station["repair_cost_limit_cents"] if station else None
        if limit_cents is None or spend < limit_cents:
            raise err("ERR_REPAIR_LIMIT_NOT_MET", "Qualifying repair spend is below the limit.")
        rec["qualifying_spend_cents"] = spend
        rec["status"] = "APPROVED"
    else:  # DENY
        rec["qualifying_spend_cents"] = spend
        rec["status"] = "DENIED"

    db.touch(rec)
    return object_response(serialize(rec), 200)


# ============================================================================
# Certificate (PRD §3.10)
# ============================================================================
@app.route("/certificates", methods=["POST"])
def create_certificate():
    _, role = authenticate()
    authorize(role, {"StationManager"})
    body = get_json_body()
    record_id = require_str(body, "record_id")
    record = lookup(db.inspection_records, record_id)
    expected_version = require_int(body, "expected_record_version")

    # OCC (priority 6, before business rules per §2.9).
    if expected_version != record["version"]:
        raise err("ERR_STALE_VERSION", "Inspection record version is stale.")

    # Business: record must be PASSED (priority 13).
    if record["status"] != "PASSED":
        raise err("ERR_RECORD_NOT_PASSED", "Record is not PASSED.")

    # At most one ACTIVE certificate per record (priority 14).
    for c in db.certificates.values():
        if c["record_id"] == record_id and c["status"] == "ACTIVE":
            raise err("ERR_CERTIFICATE_EXISTS", "An active certificate already exists for this record.")

    station = db.stations.get(record["station_id"])
    seq = station["next_certificate_seq"]
    serial = "%s%06d" % (station["certificate_serial_prefix"], seq)
    station["next_certificate_seq"] = seq + 1
    db.touch(station)

    issued_at = db.now()
    expires_on = issued_at.replace(year=issued_at.year + 1)

    rec = {
        "record_id": record_id,
        "serial": serial,
        "sticker_number": "STK-%s" % db.new_id()[:12].upper(),
        "status": "ACTIVE",
        "expires_on": _iso(expires_on),
    }
    db.stamp_create(rec)
    db.certificates[rec["id"]] = rec

    # Bump the certified record's version (PRD §3.10).
    db.touch(record)

    return object_response(serialize(rec), 201)


@app.route("/certificates/<rid>", methods=["GET"])
def get_certificate(rid):
    _, role = authenticate()
    authorize(role, {"StationManager", "Inspector", "StateAuditor"})
    rec = lookup(db.certificates, rid)
    return object_response(serialize(rec), 200)


@app.route("/certificates", methods=["GET"])
def list_certificates():
    _, role = authenticate()
    authorize(role, {"StationManager", "Inspector", "StateAuditor"})
    record_id = request.args.get("record_id")
    status = request.args.get("status")

    def pred(r):
        if record_id is not None and r["record_id"] != record_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    items, limit, offset, total = list_and_paginate(db.certificates.values(), pred)
    return array_response(items, limit, offset, total, 200)


@app.route("/certificates/<rid>/void", methods=["POST"])
def void_certificate(rid):
    _, role = authenticate()
    authorize(role, {"StationManager"})
    rec = lookup(db.certificates, rid)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Certificate is not ACTIVE.")
    rec["status"] = "VOID"
    rec["sticker_number"] = None
    db.touch(rec)
    return object_response(serialize(rec), 200)


# ============================================================================
# StateReportBatch + StateReportLine (PRD §3.11, §3.12)
# ============================================================================
@app.route("/state-report-batches", methods=["POST"])
def create_batch():
    _, role = authenticate()
    authorize(role, {"StationManager"})
    body = get_json_body()
    station_id = require_str(body, "station_id")
    lookup(db.stations, station_id)
    period_label = require_str(body, "period_label")
    rec = {
        "station_id": station_id,
        "period_label": period_label,
        "status": "OPEN",
        "line_count": 0,
        "total_reported_fee_cents": 0,
    }
    db.stamp_create(rec)
    db.state_report_batches[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/state-report-batches/<rid>", methods=["GET"])
def get_batch(rid):
    _, role = authenticate()
    authorize(role, {"StationManager", "StateAuditor"})
    rec = lookup(db.state_report_batches, rid)
    return object_response(serialize(rec), 200)


@app.route("/state-report-batches", methods=["GET"])
def list_batches():
    _, role = authenticate()
    authorize(role, {"StationManager", "StateAuditor"})
    station_id = request.args.get("station_id")
    status = request.args.get("status")

    def pred(r):
        if station_id is not None and r["station_id"] != station_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    items, limit, offset, total = list_and_paginate(db.state_report_batches.values(), pred)
    return array_response(items, limit, offset, total, 200)


def _recompute_batch(batch):
    line_count, total = calc.compute_batch_totals(batch["id"])
    batch["line_count"] = line_count
    batch["total_reported_fee_cents"] = total


@app.route("/state-report-batches/<rid>/lines", methods=["POST"])
def attach_line(rid):
    _, role = authenticate()
    authorize(role, {"StationManager"})
    batch = lookup(db.state_report_batches, rid)
    body = get_json_body()
    record_id = require_str(body, "record_id")
    record = lookup(db.inspection_records, record_id)

    # State: batch must be OPEN (lines editable only while OPEN).
    if batch["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Batch is not OPEN.")

    # Eligibility (priority 17): terminal record (PASSED/FAILED), at most once per batch.
    if record["status"] not in ("PASSED", "FAILED"):
        raise err("ERR_LINE_NOT_ELIGIBLE", "Record is not in a terminal pass/fail state.")
    for ln in db.state_report_lines.values():
        if ln["batch_id"] == rid and ln["record_id"] == record_id:
            raise err("ERR_LINE_NOT_ELIGIBLE", "Record already appears on this batch.")

    reported_result = "PASS" if record["status"] == "PASSED" else "FAIL"
    line = {
        "batch_id": rid,
        "record_id": record_id,
        "reported_result": reported_result,
        "fee_cents": record["fee_cents"],
    }
    # StateReportLine: id + created_at only (PRD §2.4 exception).
    db.stamp_create(line, with_version=False)
    db.state_report_lines[line["id"]] = line

    _recompute_batch(batch)
    db.touch(batch)

    return object_response(serialize(line), 201)


@app.route("/state-report-batches/<rid>/lines", methods=["GET"])
def list_batch_lines(rid):
    _, role = authenticate()
    authorize(role, {"StationManager", "StateAuditor"})
    lookup(db.state_report_batches, rid)
    items, limit, offset, total = list_and_paginate(
        db.state_report_lines.values(), lambda ln: ln["batch_id"] == rid)
    return array_response(items, limit, offset, total, 200)


@app.route("/state-report-lines/<rid>", methods=["GET"])
def get_state_report_line(rid):
    _, role = authenticate()
    authorize(role, {"StationManager", "StateAuditor"})
    rec = lookup(db.state_report_lines, rid)
    return object_response(serialize(rec), 200)


@app.route("/state-report-lines", methods=["GET"])
def list_state_report_lines():
    _, role = authenticate()
    authorize(role, {"StationManager", "StateAuditor"})
    record_id = request.args.get("record_id")
    batch_id = request.args.get("batch_id")

    def pred(r):
        if record_id is not None and r["record_id"] != record_id:
            return False
        if batch_id is not None and r["batch_id"] != batch_id:
            return False
        return True

    items, limit, offset, total = list_and_paginate(db.state_report_lines.values(), pred)
    return array_response(items, limit, offset, total, 200)


@app.route("/state-report-batches/<rid>/lines/<record_id>", methods=["DELETE"])
def detach_line(rid, record_id):
    _, role = authenticate()
    authorize(role, {"StationManager"})
    batch = lookup(db.state_report_batches, rid)
    # State: batch must be OPEN to edit lines.
    if batch["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Batch is not OPEN.")
    # Find the line for this record on this batch.
    target = None
    for ln in db.state_report_lines.values():
        if ln["batch_id"] == rid and ln["record_id"] == record_id:
            target = ln
            break
    if target is None:
        raise err("ERR_NOT_FOUND", "No line for this record on the batch.")
    del db.state_report_lines[target["id"]]
    _recompute_batch(batch)
    db.touch(batch)
    return object_response(serialize(batch), 200)


@app.route("/state-report-batches/<rid>/submit", methods=["POST"])
def submit_batch(rid):
    _, role = authenticate()
    authorize(role, {"StationManager"})
    batch = lookup(db.state_report_batches, rid)
    body = get_json_body()
    expected_version = require_int(body, "expected_batch_version")

    # State: must be OPEN (priority 5).
    if batch["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Batch is not OPEN.")
    # OCC (priority 6).
    if expected_version != batch["version"]:
        raise err("ERR_STALE_VERSION", "Batch version is stale.")
    # Non-empty (priority 18).
    if batch["line_count"] < 1:
        raise err("ERR_EMPTY_BATCH", "Batch has no lines.")

    batch["status"] = "SUBMITTED"
    db.touch(batch)
    return object_response(serialize(batch), 200)


@app.route("/state-report-batches/<rid>/decide", methods=["POST"])
def decide_batch(rid):
    _, role = authenticate()
    authorize(role, {"StateAuditor"})
    batch = lookup(db.state_report_batches, rid)
    body = get_json_body()
    decision = require(body, "decision")
    if not isinstance(decision, str):
        raise err("ERR_INVALID_REQUEST", "decision must be a string.")
    decision_upper = decision.upper()
    if decision_upper not in ("ACCEPT", "REJECT"):
        raise err("ERR_INVALID_REQUEST", "decision must be ACCEPT or REJECT.")
    if batch["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Batch is not SUBMITTED.")
    batch["status"] = "ACCEPTED" if decision_upper == "ACCEPT" else "REJECTED"
    db.touch(batch)
    return object_response(serialize(batch), 200)


@app.route("/state-report-batches/<rid>/reopen", methods=["POST"])
def reopen_batch(rid):
    _, role = authenticate()
    authorize(role, {"StationManager"})
    batch = lookup(db.state_report_batches, rid)
    if batch["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE", "Batch is not REJECTED.")
    batch["status"] = "OPEN"
    db.touch(batch)
    return object_response(serialize(batch), 200)


# ============================================================================
# Datetime serialization helper
# ============================================================================
def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
