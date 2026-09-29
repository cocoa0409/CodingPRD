"""Perfusion devices, immutable event logs and preventive service."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import constants as C
import serialize
import svc
import valid as V
from auth import (ROLE_BIOMED, ROLE_CHIEF, ROLE_CONTRACT_ADMIN, ROLE_PERFUSIONIST, endpoint)
from envelope import ok, ok_list
from errors import ApiError
from store import db, insert, ordered, stamp_new, touch

D = Decimal
bp = Blueprint("devices", __name__)

DEVICE_READ = (ROLE_CONTRACT_ADMIN, ROLE_CHIEF, ROLE_PERFUSIONIST, ROLE_BIOMED)


@bp.post("/perfusion-devices")
@endpoint([ROLE_BIOMED, ROLE_CONTRACT_ADMIN])
def commission_device(actor):
    body = V.payload()
    V.require(body, "contract_id", "asset_tag", "device_class")
    row = {
        "contract_id": V.vstr(body, "contract_id", required=True),
        "asset_tag": V.vstr(body, "asset_tag", required=True),
        "device_class": V.venum(body, "device_class", C.DEVICE_CLASSES, required=True),
        "status": "AVAILABLE",
        "backup_device_id": V.vstr(body, "backup_device_id"),
        "service_interval_hours": V.vint(body, "service_interval_hours", minimum=1, default=500),
        "runtime_hours_since_service": D(0),
        "alarm_count_since_service": 0,
        "last_service_completed_at": None,
    }
    svc.get_contract(row["contract_id"])
    backup = None
    if row["backup_device_id"] is not None:
        backup = svc.get_device(row["backup_device_id"])
        if (backup["device_class"] != row["device_class"]
                or backup["contract_id"] != row["contract_id"]):
            raise ApiError("ERR_INVALID_BACKUP_DEVICE")
    for other in db.perfusion_devices.values():
        if other["asset_tag"] == row["asset_tag"]:
            raise ApiError("ERR_DUPLICATE_CODE")
    stamp_new(row)
    insert("perfusion_devices", row)
    return ok(serialize.device(row), 201)


@bp.get("/perfusion-devices/<did>")
@endpoint(DEVICE_READ)
def read_device(actor, did):
    return ok(serialize.device(svc.get_device(did)))


@bp.get("/perfusion-devices")
@endpoint(DEVICE_READ)
def list_devices(actor):
    limit, offset = V.pagination()
    rows = ordered("perfusion_devices")
    for key in ("contract_id", "device_class", "status", "backup_device_id"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return ok_list([serialize.device(r) for r in V.page(rows, limit, offset)],
                   limit, offset, len(rows))


@bp.post("/perfusion-devices/<did>/event-logs")
@endpoint([ROLE_BIOMED, ROLE_PERFUSIONIST, ROLE_CHIEF])
def capture_event(actor, did):
    body = V.payload()
    V.require(body, "event_code")
    event_code = V.venum(body, "event_code", C.DEVICE_EVENT_CODES, required=True)
    delta = V.vnum(body, "runtime_hours_delta", minimum=0, maximum=24, default=D(0))
    detail = V.vstr(body, "detail", max_len=400, allow_empty=True)
    device = svc.get_device(did)

    log = svc.append_event_log(did, event_code, actor.user_id, detail, calc.num(delta))

    if event_code == "RUNTIME_TICK":
        device["runtime_hours_since_service"] = D(device["runtime_hours_since_service"]) + D(delta)
        touch(device)
    if event_code in ("ALARM_CRITICAL", "ALARM_ADVISORY", "SELF_TEST_FAIL"):
        device["alarm_count_since_service"] += 1
        touch(device)
    if event_code in ("ALARM_CRITICAL", "SELF_TEST_FAIL"):
        if device["status"] in ("AVAILABLE", "RESERVED", "IN_USE"):
            device["status"] = "NEEDS_SERVICE"
            touch(device)
            svc.critical_alarm_cascade(device)

    return ok(serialize.event_log(log), 201)


@bp.get("/perfusion-devices/<did>/event-logs")
@endpoint(DEVICE_READ)
def list_event_logs(actor, did):
    limit, offset = V.pagination()
    svc.get_device(did)
    rows = [r for r in ordered("device_event_logs") if r["device_id"] == did]
    event_code = request.args.get("event_code")
    if event_code is not None:
        rows = [r for r in rows if r["event_code"] == event_code]
    return ok_list([serialize.event_log(r) for r in V.page(rows, limit, offset)],
                   limit, offset, len(rows))


@bp.post("/perfusion-devices/<did>/service-completions")
@endpoint([ROLE_BIOMED])
def service_completion(actor, did):
    body = V.payload()
    detail = V.vstr(body, "detail", max_len=400, allow_empty=True)
    device = svc.get_device(did)
    if device["status"] != "NEEDS_SERVICE" or calc.device_open_reservation_count(did) != 0:
        raise ApiError("ERR_DEVICE_SERVICE_NOT_PERMITTED")
    device["status"] = "AVAILABLE"
    device["alarm_count_since_service"] = 0
    device["runtime_hours_since_service"] = D(0)
    device["last_service_completed_at"] = db.now()
    touch(device)
    svc.append_event_log(did, "SERVICE_COMPLETED", actor.user_id, detail, 0)
    return ok(serialize.device(device))
