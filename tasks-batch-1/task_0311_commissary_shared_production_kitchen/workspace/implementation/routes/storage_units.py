"""Storage units, temperature logging/certification, and unit compliance clear."""
from flask import Blueprint, request

from db import db, LOCK
from errors import ApiError
from middleware import get_identity, require_roles, get_json_body, parse_pagination
from response import success, paginated
from services.common import (
    stamp_new, stamp_new_append_only, touch, public, get_or_404,
    sorted_by_creation, paginate, require_fields, as_int, as_number, parse_dt,
)
from services.temperature import recompute_unit

bp = Blueprint("storage_units", __name__)

TEMP_CLASSES = {"DRY", "COLD", "FROZEN"}


@bp.post("/storage-units")
def create_storage_unit():
    _, role = get_identity()
    require_roles(role, {"FacilityManager"})
    body = get_json_body()
    require_fields(body, ["name", "temp_class", "total_slots", "temp_min_c", "temp_max_c"])
    if not isinstance(body["name"], str) or not body["name"]:
        raise ApiError("ERR_INVALID_REQUEST")
    if body["temp_class"] not in TEMP_CLASSES:
        raise ApiError("ERR_INVALID_REQUEST")
    total_slots = as_int(body["total_slots"])
    if total_slots < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    temp_min = as_number(body["temp_min_c"])
    temp_max = as_number(body["temp_max_c"])
    with LOCK:
        unit = {
            "name": body["name"],
            "temp_class": body["temp_class"],
            "total_slots": total_slots,
            "used_slots": 0,
            "temp_min_c": temp_min,
            "temp_max_c": temp_max,
            "compliance_status": "COMPLIANT",
            "excursion_minutes": 0,
        }
        stamp_new(unit)
        db.storage_units[unit["id"]] = unit
        return success(public(unit), 201)


@bp.get("/storage-units")
def list_storage_units():
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager", "ComplianceOfficer"})
    limit, offset = parse_pagination()
    temp_class = request.args.get("temp_class")
    compliance_status = request.args.get("compliance_status")
    with LOCK:
        records = sorted_by_creation(list(db.storage_units.values()))
        if temp_class:
            records = [u for u in records if u["temp_class"] == temp_class]
        if compliance_status:
            records = [u for u in records if u["compliance_status"] == compliance_status]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.get("/storage-units/<unit_id>")
def get_storage_unit(unit_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager", "ComplianceOfficer"})
    with LOCK:
        unit = get_or_404(db.storage_units, unit_id)
        return success(public(unit))


@bp.post("/storage-units/<unit_id>/temp-logs")
def create_temp_log(unit_id):
    _, role = get_identity()
    require_roles(role, {"ComplianceOfficer", "FacilityManager"})
    body = get_json_body()
    with LOCK:
        unit = get_or_404(db.storage_units, unit_id)
        require_fields(body, ["reading_c", "reading_utc"])
        reading_c = as_number(body["reading_c"])
        reading_dt = parse_dt(body["reading_utc"])
        if reading_dt is None:
            raise ApiError("ERR_INVALID_REQUEST")
        in_range = unit["temp_min_c"] <= reading_c <= unit["temp_max_c"]
        log = {
            "storage_unit_id": unit_id,
            "reading_c": reading_c,
            "reading_utc": body["reading_utc"],
            "in_range": in_range,
            "certified": False,
        }
        stamp_new_append_only(log)
        db.temp_logs[log["id"]] = log
        recompute_unit(unit)
        return success(public(log), 201)


@bp.get("/storage-units/<unit_id>/temp-logs")
def list_unit_temp_logs(unit_id):
    _, role = get_identity()
    require_roles(role, {"ComplianceOfficer", "FacilityManager"})
    limit, offset = parse_pagination()
    in_range = request.args.get("in_range")
    with LOCK:
        get_or_404(db.storage_units, unit_id)
        records = [t for t in db.temp_logs.values() if t["storage_unit_id"] == unit_id]
        records = sorted_by_creation(records)
        if in_range is not None:
            want = in_range.lower() == "true"
            records = [t for t in records if t["in_range"] == want]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.post("/storage-units/<unit_id>/temp-logs/<log_id>/certify")
def certify_temp_log(unit_id, log_id):
    _, role = get_identity()
    require_roles(role, {"ComplianceOfficer"})
    with LOCK:
        get_or_404(db.storage_units, unit_id)
        log = get_or_404(db.temp_logs, log_id)
        if log["storage_unit_id"] != unit_id:
            raise ApiError("ERR_NOT_FOUND")
        log["certified"] = True
        return success(public(log))


@bp.post("/storage-units/<unit_id>/certify-compliant")
def certify_compliant(unit_id):
    _, role = get_identity()
    require_roles(role, {"ComplianceOfficer"})
    with LOCK:
        unit = get_or_404(db.storage_units, unit_id)
        if unit["compliance_status"] != "QUARANTINED":
            raise ApiError("ERR_INVALID_STATE")
        # Latest reading (by reading_utc, tie-break created_at) must be in range.
        logs = [t for t in db.temp_logs.values() if t["storage_unit_id"] == unit_id]
        if logs:
            logs.sort(key=lambda t: (parse_dt(t["reading_utc"]), t["_seq"]))
            latest = logs[-1]
            if not latest["in_range"]:
                raise ApiError("ERR_UNIT_NOT_RECOVERED")
        unit["compliance_status"] = "COMPLIANT"
        unit["excursion_minutes"] = 0
        touch(unit)
        return success(public(unit))
