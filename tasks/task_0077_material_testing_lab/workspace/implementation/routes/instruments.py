"""Instrument routes: ledger CRUD, calibration patch, report-failure /
return-to-service / retire; bookings create + list."""

from flask import Blueprint, request

from db import DB, new_id, LOCK
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE,
    ERR_BOOKING_OUTSIDE_CALIBRATION, ERR_INSTRUMENT_SLOT_CONFLICT,
    raise_error,
)
from middleware import auth_required
from response import success_response, list_response, empty_204
from services.common import (
    get_json_body, require_fields, check_version, bump_version,
    parse_pagination, paginate,
)
from services.serializers import serialize_instrument, serialize_booking
from services.time_util import now_iso, now_dt, parse_iso, format_iso
from services.state import cascade_instrument_out_of_service

bp = Blueprint("instruments", __name__)

VALID_METHODS = {"COMPRESSION_STRENGTH", "TENSILE_STRENGTH", "COMPACTION_DENSITY",
                 "MARSHALL_STABILITY", "SETTING_TIME"}


def _parse_dt_field(v, name):
    try:
        return parse_iso(v)
    except Exception:
        raise_error(ERR_VALIDATION, f"{name} invalid datetime")


@bp.post("/instruments")
@auth_required(["LabManager"])
def create_instrument():
    body = get_json_body()
    require_fields(body, ["asset_code", "capabilities", "calibration_valid_from", "calibration_valid_to"])
    asset_code = body["asset_code"]
    if not isinstance(asset_code, str) or not asset_code:
        raise_error(ERR_VALIDATION, "asset_code required")
    capabilities = body["capabilities"]
    if not isinstance(capabilities, list) or not all(c in VALID_METHODS for c in capabilities):
        raise_error(ERR_VALIDATION, "capabilities must be a list of valid test_methods")
    cvf = _parse_dt_field(body["calibration_valid_from"], "calibration_valid_from")
    cvt = _parse_dt_field(body["calibration_valid_to"], "calibration_valid_to")
    if cvf > cvt:
        raise_error(ERR_VALIDATION, "calibration_valid_from must be <= calibration_valid_to")
    with LOCK:
        # Enforce asset_code uniqueness
        for r in DB["instruments"].values():
            if r["asset_code"] == asset_code:
                raise_error(ERR_VALIDATION, "asset_code already exists")
        now = now_iso()
        # Determine initial status: AVAILABLE unless current time is past cvt
        status = "AVAILABLE"
        if now_dt() > cvt:
            status = "CALIBRATION_DUE"
        row = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "asset_code": asset_code,
            "capabilities": capabilities,
            "calibration_valid_from": format_iso(cvf),
            "calibration_valid_to": format_iso(cvt),
            "status": status,
            "usage_minutes_total": 0,
        }
        DB["instruments"][row["id"]] = row
    return success_response(serialize_instrument(row), 201)


@bp.get("/instruments/<iid>")
@auth_required(["LabManager", "LabClerk", "Tester"])
def read_instrument(iid):
    row = DB["instruments"].get(iid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Instrument not found")
    return success_response(serialize_instrument(row), 200)


@bp.patch("/instruments/<iid>")
@auth_required(["LabManager"])
def update_instrument(iid):
    body = get_json_body()
    row = DB["instruments"].get(iid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Instrument not found")
    check_version(body, row)
    with LOCK:
        row = DB["instruments"].get(iid)
        if row is None:
            raise_error(ERR_NOT_FOUND, "Instrument not found")
        check_version(body, row)
        changed = False
        new_cvf = parse_iso(row["calibration_valid_from"]) if isinstance(row["calibration_valid_from"], str) else row["calibration_valid_from"]
        new_cvt = parse_iso(row["calibration_valid_to"]) if isinstance(row["calibration_valid_to"], str) else row["calibration_valid_to"]
        if "calibration_valid_from" in body:
            new_cvf = _parse_dt_field(body["calibration_valid_from"], "calibration_valid_from")
            row["calibration_valid_from"] = format_iso(new_cvf)
            changed = True
        if "calibration_valid_to" in body:
            new_cvt = _parse_dt_field(body["calibration_valid_to"], "calibration_valid_to")
            row["calibration_valid_to"] = format_iso(new_cvt)
            changed = True
        if new_cvf > new_cvt:
            raise_error(ERR_VALIDATION, "calibration_valid_from must be <= calibration_valid_to")
        if "capabilities" in body:
            caps = body["capabilities"]
            if not isinstance(caps, list) or not all(c in VALID_METHODS for c in caps):
                raise_error(ERR_VALIDATION, "capabilities invalid")
            row["capabilities"] = caps
            changed = True
        if changed:
            bump_version(row)
            # CALIBRATION_DUE -> AVAILABLE if the new window encloses now()
            if row.get("status") == "CALIBRATION_DUE":
                if new_cvf <= now_dt() <= new_cvt:
                    row["status"] = "AVAILABLE"
    return success_response(serialize_instrument(row), 200)


@bp.post("/instruments/<iid>/report-failure")
@auth_required(["LabManager"])
def report_failure(iid):
    row = DB["instruments"].get(iid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Instrument not found")
    if row.get("status") != "AVAILABLE":
        raise_error(ERR_INVALID_STATE, "Instrument must be AVAILABLE to be reported failed")
    with LOCK:
        cascade_instrument_out_of_service(row, now_dt=now_dt())
    return success_response(serialize_instrument(row), 200)


@bp.post("/instruments/<iid>/return-to-service")
@auth_required(["LabManager"])
def return_to_service(iid):
    row = DB["instruments"].get(iid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Instrument not found")
    if row.get("status") != "OUT_OF_SERVICE":
        raise_error(ERR_INVALID_STATE, "Instrument must be OUT_OF_SERVICE to return to service")
    with LOCK:
        row["status"] = "AVAILABLE"
        bump_version(row)
    return success_response(serialize_instrument(row), 200)


@bp.delete("/instruments/<iid>")
@auth_required(["LabManager"])
def retire_instrument(iid):
    row = DB["instruments"].get(iid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Instrument not found")
    with LOCK:
        for b in DB["bookings"].values():
            if b.get("instrument_id") == iid and b.get("status") == "RESERVED":
                raise_error(ERR_INVALID_STATE, "Instrument has RESERVED bookings")
        row["status"] = "RETIRED"
        bump_version(row)
    return empty_204()


# ----- Bookings -----

def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


@bp.post("/instruments/<iid>/bookings")
@auth_required(["LabClerk", "Tester"])
def create_booking(iid):
    body = get_json_body()
    instrument = DB["instruments"].get(iid)
    if instrument is None:
        raise_error(ERR_NOT_FOUND, "Instrument not found")
    require_fields(body, ["task_id", "slot_start", "slot_end"])
    task_id = body["task_id"]
    task = DB["tasks"].get(task_id)
    if task is None:
        raise_error(ERR_NOT_FOUND, "Task not found")
    try:
        slot_start = parse_iso(body["slot_start"])
        slot_end = parse_iso(body["slot_end"])
    except Exception:
        raise_error(ERR_VALIDATION, "slot_start/slot_end must be ISO datetimes")
    # Calibration window check: half-open interval entirely within
    # [calibration_valid_from, calibration_valid_to].
    cvf = parse_iso(instrument["calibration_valid_from"]) if isinstance(instrument["calibration_valid_from"], str) else instrument["calibration_valid_from"]
    cvt = parse_iso(instrument["calibration_valid_to"]) if isinstance(instrument["calibration_valid_to"], str) else instrument["calibration_valid_to"]
    if not (slot_start < slot_end):
        raise_error(ERR_BOOKING_OUTSIDE_CALIBRATION, "slot_start must be before slot_end")
    if slot_start < cvf or slot_end > cvt:
        raise_error(ERR_BOOKING_OUTSIDE_CALIBRATION, "Booking outside calibration window")
    with LOCK:
        # Overlap check
        for b in DB["bookings"].values():
            if b.get("instrument_id") != iid:
                continue
            if b.get("status") not in ("RESERVED", "COMPLETED"):
                continue
            other_start = parse_iso(b["slot_start"]) if isinstance(b["slot_start"], str) else b["slot_start"]
            other_end = parse_iso(b["slot_end"]) if isinstance(b["slot_end"], str) else b["slot_end"]
            if _intervals_overlap(slot_start, slot_end, other_start, other_end):
                raise_error(ERR_INSTRUMENT_SLOT_CONFLICT, "Booking overlaps an existing reservation")
        now = now_iso()
        booking = {
            "id": new_id(),
            "created_at": now,
            "instrument_id": iid,
            "task_id": task_id,
            "slot_start": format_iso(slot_start),
            "slot_end": format_iso(slot_end),
            "status": "RESERVED",
        }
        DB["bookings"][booking["id"]] = booking
        # Write back to the task
        task["instrument_booking_id"] = booking["id"]
        from services.state import touch as _touch
        _touch(task)
    return success_response(serialize_booking(booking), 201)


@bp.get("/instruments/<iid>/bookings")
@auth_required(["LabManager", "LabClerk"])
def list_bookings(iid):
    if iid not in DB["instruments"]:
        raise_error(ERR_NOT_FOUND, "Instrument not found")
    limit, offset = parse_pagination()
    from_q = request.args.get("from")
    to_q = request.args.get("to")
    from_dt = parse_iso(from_q) if from_q else None
    to_dt = parse_iso(to_q) if to_q else None
    rows = [b for b in DB["bookings"].values() if b.get("instrument_id") == iid]
    if from_dt is not None:
        rows = [b for b in rows
                if (parse_iso(b["slot_end"]) if isinstance(b["slot_end"], str) else b["slot_end"]) > from_dt]
    if to_dt is not None:
        rows = [b for b in rows
                if (parse_iso(b["slot_start"]) if isinstance(b["slot_start"], str) else b["slot_start"]) < to_dt]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return list_response([serialize_booking(r) for r in page], total, limit, offset)
