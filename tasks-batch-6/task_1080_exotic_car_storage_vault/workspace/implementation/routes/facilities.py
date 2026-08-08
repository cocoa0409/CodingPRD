"""Facility, StorageUnit, and logical clock routes."""
from flask import Blueprint

import core
from core import (
    db, require, get_body, get_or_404, base_record, touch, success,
    list_response, req_str, req_int, req_enum, req_bool, req_dt, ApiError,
    parse_iso,
)
from services import (
    ser_facility, ser_unit, facility_counts, run_waitlist_promotion,
)

bp = Blueprint("facilities", __name__)

UNIT_CLASSES = {"STANDARD", "CLIMATE", "SHOWCASE"}
UNIT_STATUSES = {"AVAILABLE", "RESERVED", "OCCUPIED", "OUT_OF_SERVICE"}


@bp.post("/facilities")
def create_facility():
    require("VaultManager")
    body = get_body()
    name = req_str(body, "name")
    total_units = req_int(body, "total_units", minimum=0)
    rec = base_record()
    rec.update({"name": name, "total_units": total_units})
    db.facilities[rec["id"]] = rec
    return success(ser_facility(rec), status=201)


@bp.get("/facilities/<fid>")
def get_facility(fid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    rec = get_or_404(db.facilities, fid)
    return success(ser_facility(rec))


@bp.get("/facilities/<fid>/units")
def list_facility_units(fid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    get_or_404(db.facilities, fid)
    from flask import request
    status = request.args.get("status")
    units = [u for u in db.units.values() if u["facility_id"] == fid
             and (status is None or u["status"] == status)]
    return list_response(units, ser_unit)


@bp.post("/facilities/<fid>/units")
def create_unit(fid):
    require("VaultManager")
    facility = get_or_404(db.facilities, fid)
    body = get_body()
    unit_code = req_str(body, "unit_code")
    unit_class = req_enum(body, "unit_class", UNIT_CLASSES)
    monthly_rate_cents = req_int(body, "monthly_rate_cents", minimum=0)
    # Uniqueness (priority 5) before facility ceiling (priority 15).
    for u in db.units.values():
        if u["facility_id"] == fid and u["unit_code"] == unit_code:
            raise ApiError("ERR_DUPLICATE", 409, "unit_code already used at this facility")
    existing = sum(1 for u in db.units.values() if u["facility_id"] == fid)
    if existing >= facility["total_units"]:
        raise ApiError("ERR_FACILITY_UNIT_LIMIT", 409, "Facility unit ceiling reached")
    rec = base_record()
    rec.update({
        "facility_id": fid,
        "unit_code": unit_code,
        "unit_class": unit_class,
        "monthly_rate_cents": monthly_rate_cents,
        "status": "AVAILABLE",
    })
    db.units[rec["id"]] = rec
    return success(ser_unit(rec), status=201)


@bp.get("/units/<uid>")
def get_unit(uid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    rec = get_or_404(db.units, uid)
    return success(ser_unit(rec))


@bp.post("/units/<uid>/set-service-status")
def set_service_status(uid):
    require("VaultManager")
    unit = get_or_404(db.units, uid)
    body = get_body()
    in_service = req_bool(body, "in_service")
    if in_service:
        if unit["status"] != "OUT_OF_SERVICE":
            raise ApiError("ERR_INVALID_STATE", 409, "Unit is not OUT_OF_SERVICE")
        unit["status"] = "AVAILABLE"
        touch(unit)
        run_waitlist_promotion(unit)
    else:
        if unit["status"] != "AVAILABLE":
            raise ApiError("ERR_INVALID_STATE", 409, "Unit is not AVAILABLE")
        unit["status"] = "OUT_OF_SERVICE"
        touch(unit)
    return success(ser_unit(unit))


@bp.post("/_clock/set_current_utc")
def set_clock():
    require("VaultManager", "BillingAdmin")
    body = get_body()
    if "to_iso8601" not in body:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Missing required field: to_iso8601")
    try:
        db.clock = parse_iso(body["to_iso8601"])
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 422, "to_iso8601 must be an ISO 8601 UTC datetime")
    return success({})
