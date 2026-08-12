"""Meter inventory endpoints (PRD 3.2)."""
import db
from db import base_resource, touch
from errors import raise_err
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.core import get_or_404, list_page, ser_meter
from flask import Blueprint, request
from validate import body, req_dt, req_enum, req_int, req_str

bp = Blueprint("meters", __name__)

SIZE_CODES = ("S_5_8", "S_3_4", "S_1", "S_1_5", "S_2")
TECHNOLOGIES = ("LEGACY", "AMI")


@bp.post("/api/meters")
@require_roles("Scheduler")
def create_meter():
    b = body()
    serial_number = req_str(b, "serial_number")
    size_code = req_enum(b, "size_code", SIZE_CODES)
    technology = req_enum(b, "technology", TECHNOLOGIES)
    for m in db.meters.values():
        if m["serial_number"] == serial_number:
            raise_err("ERR_METER_SERIAL_CONFLICT", "serial_number already registered")
    m = base_resource()
    m.update({
        "serial_number": serial_number,
        "size_code": size_code,
        "technology": technology,
        "service_account_id": None,
        "installed_read_value": None,
        "status": "IN_STOCK",
    })
    db.meters[m["id"]] = m
    return ok_object(ser_meter(m), 201)


@bp.get("/api/meters")
@require_roles(*ALL_ROLES)
def list_meters():
    filters = {}
    for k in ("service_account_id", "status", "technology"):
        if request.args.get(k) is not None:
            filters[k] = request.args[k]
    return list_page(db.meters.values(), filters, ser_meter)


@bp.get("/api/meters/<meterId>")
@require_roles(*ALL_ROLES)
def get_meter(meterId):
    return ok_object(ser_meter(get_or_404(db.meters, meterId, "Meter")))


@bp.post("/api/meters/<meterId>/install")
@require_roles("Scheduler")
def install_meter(meterId):
    m = get_or_404(db.meters, meterId, "Meter")
    b = body()
    account_id = b.get("service_account_id")
    account = None
    if isinstance(account_id, str):
        account = get_or_404(db.accounts, account_id, "ServiceAccount")
    account_id = req_str(b, "service_account_id")
    if account is None:
        account = get_or_404(db.accounts, account_id, "ServiceAccount")
    initial_read = req_int(b, "initial_read_value", min=0)
    req_dt(b, "installed_at")
    # State (stage 7): only an IN_STOCK meter can be installed.
    if m["status"] != "IN_STOCK":
        raise_err("ERR_INVALID_STATE", "Meter is not IN_STOCK")
    # Referential (stage 13): target account must have no INSTALLED meter.
    for other in db.meters.values():
        if other["service_account_id"] == account["id"] and other["status"] == "INSTALLED":
            raise_err("ERR_METER_NOT_AVAILABLE",
                      "Account already has an INSTALLED meter")
    m["status"] = "INSTALLED"
    m["service_account_id"] = account["id"]
    m["installed_read_value"] = initial_read
    touch(m)
    return ok_object(ser_meter(m))


@bp.post("/api/meters/<meterId>/dispose")
@require_roles("Scheduler")
def dispose_meter(meterId):
    m = get_or_404(db.meters, meterId, "Meter")
    if m["status"] == "BENCH_PASSED":
        m["status"] = "DISPOSED"
    elif m["status"] == "BENCH_FAILED":
        m["status"] = "RETURNED_TO_VENDOR"
    else:
        raise_err("ERR_INVALID_STATE",
                  "Only BENCH_PASSED or BENCH_FAILED meters can be disposed")
    touch(m)
    return ok_object(ser_meter(m))
