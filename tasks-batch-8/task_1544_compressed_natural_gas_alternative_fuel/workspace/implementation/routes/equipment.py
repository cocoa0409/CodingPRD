"""Compressor, Dispenser, CalibrationRecord endpoints."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import STORE, new_id, now_utc
from errors import (
    ApiError,
    ERR_STATION_NOT_FOUND,
    ERR_COMPRESSOR_NOT_FOUND,
    ERR_DISPENSER_NOT_FOUND,
    ERR_CALIBRATION_RECORD_NOT_FOUND,
    ERR_COMPRESSOR_UNDER_MAINTENANCE,
    ERR_INVALID_REQUEST,
)
from middleware import get_caller, require_role
from response import success_object, success_list
from serializers import compressor_out, dispenser_out, calibration_record_out
from services.core import (
    recompute_station_posture,
    touch,
    TOLERANCE_PCT,
    CALIBRATION_INTERVAL_DAYS,
    to_decimal,
    round_half_up_4,
)
from validators import (
    body, require_fields, require_string, require_enum, require_positive_int,
    parse_pagination, paginate,
)

bp = Blueprint("equipment", __name__)

_ALL_READ = ["NetworkOperator", "StationManager", "ComplianceOfficer",
             "FleetAccountManager", "FleetDriver"]


def get_compressor_or_404(cid: str) -> dict:
    c = STORE.compressors.get(cid)
    if c is None:
        raise ApiError(ERR_COMPRESSOR_NOT_FOUND, 404, "Compressor id does not exist")
    return c


def get_dispenser_or_404(did: str) -> dict:
    d = STORE.dispensers.get(did)
    if d is None:
        raise ApiError(ERR_DISPENSER_NOT_FOUND, 404, "Dispenser id does not exist")
    return d


# ---------------- Compressors ----------------

@bp.post("/cng/compressors")
def create_compressor():
    caller = get_caller()
    require_role(caller, ["StationManager"])
    data = body()
    require_fields(data, ["station_id", "compressor_code", "capacity_scf_per_minute"])
    station_id = require_string(data, "station_id")
    compressor_code = require_string(data, "compressor_code")
    capacity = require_positive_int(data, "capacity_scf_per_minute")
    if station_id not in STORE.stations:
        raise ApiError(ERR_STATION_NOT_FOUND, 404, "Station id does not exist")
    now = now_utc()
    comp = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "station_id": station_id,
        "compressor_code": compressor_code,
        "capacity_scf_per_minute": capacity,
        "condition": "ONLINE",
    }
    STORE.compressors[comp["id"]] = comp
    recompute_station_posture(station_id)
    return success_object(compressor_out(comp), status=201)


@bp.get("/cng/compressors")
def list_compressors():
    caller = get_caller()
    require_role(caller, _ALL_READ)
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    condition = request.args.get("condition")
    items = sorted(STORE.compressors.values(), key=lambda c: (c["created_at"], c["id"]))
    if station_id is not None:
        items = [c for c in items if c["station_id"] == station_id]
    if condition is not None:
        items = [c for c in items if c["condition"] == condition]
    page, total = paginate(items, limit, offset)
    return success_list([compressor_out(c) for c in page], limit, offset, total)


@bp.get("/cng/compressors/<compressorId>")
def get_compressor(compressorId: str):
    caller = get_caller()
    require_role(caller, _ALL_READ)
    return success_object(compressor_out(get_compressor_or_404(compressorId)))


@bp.post("/cng/compressors/<compressorId>/report-condition")
def report_condition(compressorId: str):
    caller = get_caller()
    require_role(caller, ["StationManager"])
    data = body()
    require_fields(data, ["condition"])
    condition = require_enum(data, "condition", {"ONLINE", "DEGRADED", "OFFLINE"})
    comp = get_compressor_or_404(compressorId)
    if comp["condition"] == "UNDER_MAINTENANCE":
        raise ApiError(ERR_COMPRESSOR_UNDER_MAINTENANCE, 409,
                       "Compressor is UNDER_MAINTENANCE")
    # Valid transitions per state machine: ONLINE->{DEGRADED,OFFLINE},
    # DEGRADED->{ONLINE,OFFLINE}, OFFLINE->{ONLINE}. Self-transitions are not
    # declared; treat same-condition report as invalid request.
    allowed = {
        "ONLINE": {"DEGRADED", "OFFLINE"},
        "DEGRADED": {"ONLINE", "OFFLINE"},
        "OFFLINE": {"ONLINE"},
    }
    if condition not in allowed.get(comp["condition"], set()):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Cannot report condition {condition} from {comp['condition']}")
    comp["condition"] = condition
    touch(comp)
    recompute_station_posture(comp["station_id"])
    return success_object(compressor_out(comp))


# ---------------- Dispensers ----------------

@bp.post("/cng/dispensers")
def create_dispenser():
    caller = get_caller()
    require_role(caller, ["StationManager"])
    data = body()
    require_fields(data, ["station_id", "dispenser_code", "fuel_type"])
    station_id = require_string(data, "station_id")
    dispenser_code = require_string(data, "dispenser_code")
    fuel_type = require_enum(data, "fuel_type", {"CNG", "RNG"})
    if station_id not in STORE.stations:
        raise ApiError(ERR_STATION_NOT_FOUND, 404, "Station id does not exist")
    now = now_utc()
    disp = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "station_id": station_id,
        "dispenser_code": dispenser_code,
        "fuel_type": fuel_type,
        "status": "IN_SERVICE",
        "correction_factor": Decimal("1.0"),
        "last_calibration_at": now,
        "calibration_due_at": now + timedelta(days=CALIBRATION_INTERVAL_DAYS),
    }
    STORE.dispensers[disp["id"]] = disp
    recompute_station_posture(station_id)
    return success_object(dispenser_out(disp), status=201)


@bp.get("/cng/dispensers")
def list_dispensers():
    caller = get_caller()
    require_role(caller, _ALL_READ)
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    fuel_type = request.args.get("fuel_type")
    items = sorted(STORE.dispensers.values(), key=lambda d: (d["created_at"], d["id"]))
    if station_id is not None:
        items = [d for d in items if d["station_id"] == station_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if fuel_type is not None:
        items = [d for d in items if d["fuel_type"] == fuel_type]
    page, total = paginate(items, limit, offset)
    return success_list([dispenser_out(d) for d in page], limit, offset, total)


@bp.get("/cng/dispensers/<dispenserId>")
def get_dispenser(dispenserId: str):
    caller = get_caller()
    require_role(caller, _ALL_READ)
    return success_object(dispenser_out(get_dispenser_or_404(dispenserId)))


# ---------------- Calibration records ----------------

@bp.post("/cng/calibration-records")
def create_calibration_record():
    caller = get_caller()
    require_role(caller, ["StationManager"])
    data = body()
    require_fields(data, ["dispenser_id", "measured_error_pct"])
    dispenser_id = require_string(data, "dispenser_id")
    raw_err = data.get("measured_error_pct")
    if isinstance(raw_err, bool) or not isinstance(raw_err, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, "measured_error_pct must be a number")
    try:
        measured = to_decimal(raw_err)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, "measured_error_pct must be numeric")

    dispenser = get_dispenser_or_404(dispenser_id)

    is_pass = abs(measured) <= TOLERANCE_PCT
    now = now_utc()
    applied_cf = None
    if is_pass:
        applied_cf = round_half_up_4(Decimal("1") - measured / Decimal("100"))
    record = {
        "id": new_id(),
        "created_at": now,
        "dispenser_id": dispenser_id,
        "measured_error_pct": measured,
        "result": "PASS" if is_pass else "FAIL",
        "applied_correction_factor": applied_cf,
        "performed_at": now,
    }
    STORE.calibration_records[record["id"]] = record

    # Apply dispenser effects per state machine
    if is_pass:
        dispenser["status"] = "IN_SERVICE"
        dispenser["correction_factor"] = applied_cf
        dispenser["last_calibration_at"] = now
        dispenser["calibration_due_at"] = now + timedelta(days=CALIBRATION_INTERVAL_DAYS)
    else:
        dispenser["status"] = "OUT_OF_SERVICE"
    touch(dispenser)
    recompute_station_posture(dispenser["station_id"])
    return success_object(calibration_record_out(record), status=201)


@bp.get("/cng/calibration-records")
def list_calibration_records():
    caller = get_caller()
    require_role(caller, _ALL_READ)
    limit, offset = parse_pagination()
    dispenser_id = request.args.get("dispenser_id")
    result = request.args.get("result")
    items = sorted(STORE.calibration_records.values(), key=lambda r: (r["created_at"], r["id"]))
    if dispenser_id is not None:
        items = [r for r in items if r["dispenser_id"] == dispenser_id]
    if result is not None:
        items = [r for r in items if r["result"] == result]
    page, total = paginate(items, limit, offset)
    return success_list([calibration_record_out(r) for r in page], limit, offset, total)


@bp.get("/cng/calibration-records/<recordId>")
def get_calibration_record(recordId: str):
    caller = get_caller()
    require_role(caller, _ALL_READ)
    r = STORE.calibration_records.get(recordId)
    if r is None:
        raise ApiError(ERR_CALIBRATION_RECORD_NOT_FOUND, 404,
                       "Calibration record id does not exist")
    return success_object(calibration_record_out(r))
