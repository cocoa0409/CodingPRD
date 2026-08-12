"""Storage units, slots, reservations, temperature readings, failure contingency."""
from flask import Blueprint

import db
from clock import parse_iso8601, now
from errors import raise_error
from middleware import (
    require_roles,
    get_json_body,
    check_known_fields,
    require_fields,
    validate_enum,
    validate_string,
    validate_number,
    validate_integer,
    parse_pagination,
    ALL_ROLES,
)
from response import success_object, success_list
from serializers import (
    storage_unit_out,
    slot_out,
    reservation_out,
    temperature_reading_out,
)
from services.common import make_record, make_audit_record, get_or_404, touch
from services.storage import (
    recompute_excursions,
    fire_failure_cascade,
    return_to_service_cascade,
    unit_readings_sorted,
)

bp = Blueprint("storage", __name__)

PURPOSES = {"MAINTENANCE", "TRANSFER_HOLD", "AUDIT"}


@bp.route("/biobank/storage-units", methods=["POST"])
def create_unit():
    require_roles({"BiobankAdmin"})
    body = get_json_body()
    check_known_fields(body, {"unit_code", "setpoint_c", "warn_threshold_c", "fail_threshold_c"})
    require_fields(body, ["unit_code", "setpoint_c"])
    unit_code = validate_string(body["unit_code"], "unit_code")
    setpoint_c = validate_number(body["setpoint_c"], "setpoint_c")
    warn = body.get("warn_threshold_c", -70.0)
    fail = body.get("fail_threshold_c", -60.0)
    validate_number(warn, "warn_threshold_c")
    validate_number(fail, "fail_threshold_c")
    unit = make_record(db.storage_units, {
        "unit_code": unit_code,
        "setpoint_c": setpoint_c,
        "warn_threshold_c": warn,
        "fail_threshold_c": fail,
        "posture": "OPERATIONAL",
        "peak_excursion_c": 0,
        "cumulative_degree_minutes": 0,
    })
    return success_object(storage_unit_out(unit), status=201)


@bp.route("/biobank/storage-units/<unitId>", methods=["GET"])
def get_unit(unitId):
    require_roles(ALL_ROLES)
    unit = get_or_404(db.storage_units, unitId, "storage unit")
    return success_object(storage_unit_out(unit))


@bp.route("/biobank/storage-units/<id>/slots", methods=["POST"])
def create_slot(id):
    require_roles({"BiobankAdmin"})
    unit = get_or_404(db.storage_units, id, "storage unit")
    body = get_json_body()
    check_known_fields(body, {"slot_code", "capacity_ml"})
    require_fields(body, ["slot_code", "capacity_ml"])
    slot_code = validate_string(body["slot_code"], "slot_code")
    capacity_ml = validate_integer(body["capacity_ml"], "capacity_ml")
    if capacity_ml <= 0:
        raise_error("ERR_INVALID_REQUEST", "capacity_ml must be > 0")
    slot = make_record(db.storage_slots, {
        "storage_unit_id": unit["id"],
        "slot_code": slot_code,
        "capacity_ml": capacity_ml,
        "status": "AVAILABLE",
    })
    return success_object(slot_out(slot), status=201)


@bp.route("/biobank/storage-units/<id>/slots", methods=["GET"])
def list_slots(id):
    require_roles(ALL_ROLES)
    unit = get_or_404(db.storage_units, id, "storage unit")
    limit, offset = parse_pagination()
    items = [s for s in db.storage_slots.values() if s["storage_unit_id"] == unit["id"]]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([slot_out(s) for s in page], limit, offset, total)


@bp.route("/biobank/storage-slots/<slotId>", methods=["GET"])
def get_slot(slotId):
    require_roles(ALL_ROLES)
    slot = get_or_404(db.storage_slots, slotId, "storage slot")
    return success_object(slot_out(slot))


@bp.route("/biobank/storage-slots/<id>/reservations", methods=["POST"])
def create_reservation(id):
    require_roles({"LabTechnician"})
    slot = get_or_404(db.storage_slots, id, "storage slot")
    body = get_json_body()
    check_known_fields(body, {"starts_at", "ends_at", "purpose"})
    require_fields(body, ["starts_at", "ends_at", "purpose"])
    starts_at = parse_iso8601(body["starts_at"], "starts_at")
    ends_at = parse_iso8601(body["ends_at"], "ends_at")
    purpose = validate_enum(body["purpose"], PURPOSES, "purpose")
    if ends_at <= starts_at:
        raise_error("ERR_INVALID_REQUEST", "ends_at must be strictly after starts_at")
    # Half-open [starts_at, ends_at) overlap against BOOKED reservations.
    if slot["status"] != "AVAILABLE":
        raise_error("ERR_SLOT_NOT_AVAILABLE", "Slot is not AVAILABLE")
    unit = db.storage_units.get(slot["storage_unit_id"])
    if unit is not None and unit["posture"] != "OPERATIONAL":
        raise_error("ERR_UNIT_NOT_OPERATIONAL", "Storage unit is not OPERATIONAL")
    for r in db.slot_reservations.values():
        if r["storage_slot_id"] != slot["id"] or r["status"] != "BOOKED":
            continue
        # Overlap iff new.starts < existing.ends AND existing.starts < new.ends.
        if starts_at < r["ends_at"] and r["starts_at"] < ends_at:
            raise_error("ERR_SLOT_RESERVATION_OVERLAP", "Reservation window overlaps an existing BOOKED reservation")
    res = make_record(db.slot_reservations, {
        "storage_slot_id": slot["id"],
        "starts_at": starts_at,
        "ends_at": ends_at,
        "purpose": purpose,
        "status": "BOOKED",
    })
    return success_object(reservation_out(res), status=201)


@bp.route("/biobank/storage-slots/<id>/reservations", methods=["GET"])
def list_reservations(id):
    require_roles(ALL_ROLES)
    slot = get_or_404(db.storage_slots, id, "storage slot")
    limit, offset = parse_pagination()
    items = [r for r in db.slot_reservations.values() if r["storage_slot_id"] == slot["id"]]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([reservation_out(r) for r in page], limit, offset, total)


@bp.route("/biobank/storage-units/<id>/temperature-readings", methods=["POST"])
def ingest_reading(id):
    require_roles({"LabTechnician"})
    unit = get_or_404(db.storage_units, id, "storage unit")
    body = get_json_body()
    check_known_fields(body, {"recorded_at", "temp_c"})
    require_fields(body, ["recorded_at", "temp_c"])
    recorded_at = parse_iso8601(body["recorded_at"], "recorded_at")
    temp_c = validate_number(body["temp_c"], "temp_c")
    if temp_c < -100.0 or temp_c > 25.0:
        raise_error("ERR_INVALID_TEMPERATURE_READING", "temp_c outside plausibility range -100.0..+25.0")
    reading = make_audit_record(db.temperature_readings, {
        "storage_unit_id": unit["id"],
        "recorded_at": recorded_at,
        "temp_c": temp_c,
    })
    # Posture transitions.
    if temp_c > unit["fail_threshold_c"]:
        if unit["posture"] != "FAILURE":
            unit["posture"] = "FAILURE"
            fire_failure_cascade(unit)
    elif temp_c > unit["warn_threshold_c"]:
        if unit["posture"] == "OPERATIONAL":
            unit["posture"] = "WARNING"
    else:
        if unit["posture"] == "WARNING":
            unit["posture"] = "OPERATIONAL"
    recompute_excursions(unit)
    touch(unit)
    return success_object(temperature_reading_out(reading), status=201)


@bp.route("/biobank/storage-units/<id>/temperature-readings", methods=["GET"])
def list_readings(id):
    require_roles(ALL_ROLES)
    unit = get_or_404(db.storage_units, id, "storage unit")
    limit, offset = parse_pagination()
    items = unit_readings_sorted(unit["id"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([temperature_reading_out(r) for r in page], limit, offset, total)


@bp.route("/biobank/storage-units/<unitId>/declare-failure", methods=["POST"])
def declare_failure(unitId):
    require_roles({"QualityOfficer"})
    unit = get_or_404(db.storage_units, unitId, "storage unit")
    body = get_json_body()
    check_known_fields(body, {"note"})
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise_error("ERR_INVALID_REQUEST", "note must be a string or null")
    if unit["posture"] == "FAILURE":
        raise_error("ERR_INVALID_STATE", "Unit is already in FAILURE")
    unit["posture"] = "FAILURE"
    fire_failure_cascade(unit)
    touch(unit)
    return success_object(storage_unit_out(unit))


@bp.route("/biobank/storage-units/<unitId>/return-to-service", methods=["POST"])
def return_to_service(unitId):
    require_roles({"QualityOfficer"})
    unit = get_or_404(db.storage_units, unitId, "storage unit")
    get_json_body()
    if unit["posture"] != "FAILURE":
        raise_error("ERR_INVALID_STATE", "Unit must be in FAILURE to return to service")
    unit["posture"] = "OPERATIONAL"
    return_to_service_cascade(unit)
    touch(unit)
    return success_object(storage_unit_out(unit))
