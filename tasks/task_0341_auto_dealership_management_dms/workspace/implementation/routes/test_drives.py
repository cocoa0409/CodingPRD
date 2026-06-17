from datetime import timedelta

from flask import Blueprint, request

import db
import response
from errors import err
from middleware import authenticate, get_user_id
from routes.lookup import get_fk, get_path
from services import serialize
from util import (base_record, get_json_body, paginate, parse_dt, parse_iso,
                  parse_pagination, require_str, touch)

bp = Blueprint("test_drives", __name__)

TURNAROUND_BUFFER = timedelta(minutes=30)


def _authz(*allowed):
    role = authenticate()
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
    return role


@bp.post("/test-drives")
def book_test_drive():
    role = _authz("SalesManager", "Customer")
    body = get_json_body()
    vehicle_id = require_str(body, "vehicle_id")
    customer_id = require_str(body, "customer_id")
    start_at = parse_dt(body, "start_at")
    end_at = parse_dt(body, "end_at")

    # Customer may only book their own test drive (customer_id == X-User-ID).
    if role == "Customer" and customer_id != get_user_id():
        raise err("ERR_FORBIDDEN", "Customer may only book their own test drive")

    # FK existence (priority 4).
    get_fk(db.vehicles, vehicle_id)
    customer = get_fk(db.customers, customer_id)

    # Temporal overlap (priority 11) precedes the license safety check (priority 13).
    new_start = start_at
    new_end = end_at
    for td in db.test_drives.values():
        if td["vehicle_id"] != vehicle_id or td["status"] != "SCHEDULED":
            continue
        ex_start = parse_iso(td["start_at"])
        ex_end = parse_iso(td["end_at"]) + TURNAROUND_BUFFER
        # half-open [start, end) overlap with buffer appended after the existing drive
        if new_start < ex_end and (new_end + TURNAROUND_BUFFER) > ex_start:
            raise err("ERR_TESTDRIVE_OVERLAP", "Test-drive interval overlaps another scheduled drive")

    # License safety (priority 13).
    if not customer["drivers_license_valid"]:
        raise err("ERR_LICENSE_INVALID", "Customer lacks a valid driver license")

    rec = base_record()
    rec.update({
        "vehicle_id": vehicle_id,
        "customer_id": customer_id,
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "status": "SCHEDULED",
    })
    db.test_drives[rec["id"]] = rec
    return response.success(serialize.test_drive(rec), status=201)


@bp.get("/test-drives/<tid>")
def get_test_drive(tid):
    role = _authz("SalesManager", "Customer")
    rec = get_path(db.test_drives, tid)
    if role == "Customer" and rec["customer_id"] != get_user_id():
        raise err("ERR_FORBIDDEN", "Customer may only read their own test drive")
    return response.success(serialize.test_drive(rec))


@bp.get("/test-drives")
def list_test_drives():
    role = _authz("SalesManager", "Customer")
    limit, offset = parse_pagination()
    items = list(db.test_drives.values())
    if role == "Customer":
        items = [t for t in items if t["customer_id"] == get_user_id()]
    vehicle_id = request.args.get("vehicle_id")
    if vehicle_id is not None:
        items = [t for t in items if t["vehicle_id"] == vehicle_id]
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [t for t in items if t["customer_id"] == customer_id]
    page, total, has_more = paginate(items, limit, offset)
    return response.success_list([serialize.test_drive(t) for t in page], limit, offset, total, has_more)


@bp.post("/test-drives/<tid>/complete")
def complete_test_drive(tid):
    _authz("SalesManager")
    rec = get_path(db.test_drives, tid)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Test drive is not SCHEDULED")
    rec["status"] = "COMPLETED"
    touch(rec)
    return response.success(serialize.test_drive(rec))


@bp.post("/test-drives/<tid>/cancel")
def cancel_test_drive(tid):
    role = _authz("SalesManager", "Customer")
    rec = get_path(db.test_drives, tid)
    if role == "Customer" and rec["customer_id"] != get_user_id():
        raise err("ERR_FORBIDDEN", "Customer may only cancel their own test drive")
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Test drive is not SCHEDULED")
    rec["status"] = "CANCELLED"
    touch(rec)
    return response.success(serialize.test_drive(rec))
