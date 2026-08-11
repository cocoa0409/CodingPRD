"""AMI endpoint registration endpoints (PRD 3.6) plus the test-driving
read-ingest capability."""
from datetime import timedelta

import db
from db import base_resource, clock_now, touch
from errors import raise_err
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.core import (
    AMI_MIN_READS,
    COMM_WINDOW_HOURS,
    RSSI_MIN_DBM,
    enter_qa_review,
    get_or_404,
    list_page,
    ser_registration,
)
from flask import Blueprint, request
from validate import body, req_dt, req_int, req_str

bp = Blueprint("registrations", __name__)


def _serial_in_use(serial):
    return any(r["endpoint_serial"] == serial
               for r in db.endpoint_registrations.values())


@bp.post("/api/endpoint-registrations")
@require_roles("AmiOperator")
def create_registration():
    b = body()
    work_order_id = b.get("work_order_id")
    if isinstance(work_order_id, str):
        get_or_404(db.work_orders, work_order_id, "WorkOrder")
    work_order_id = req_str(b, "work_order_id")
    wo = get_or_404(db.work_orders, work_order_id, "WorkOrder")
    endpoint_serial = req_str(b, "endpoint_serial")
    # Uniqueness (stage 6): endpoint_serial unique across all registrations.
    if _serial_in_use(endpoint_serial):
        raise_err("ERR_AMI_ENDPOINT_SERIAL_CONFLICT",
                  "endpoint_serial already registered")
    # State (stage 7): the work order must be RECONCILED, and at most one
    # non-REPLACED registration per work order (PRD 3.6).
    if wo["lifecycle_status"] != "RECONCILED":
        raise_err("ERR_INVALID_STATE", "Work order is not RECONCILED")
    for r in db.endpoint_registrations.values():
        if r["work_order_id"] == wo["id"] and r["status"] != "REPLACED":
            raise_err("ERR_INVALID_STATE",
                      "Work order already has an active registration")
    reg = base_resource()
    reg.update({
        "work_order_id": wo["id"],
        "meter_id": wo["new_meter_id"],
        "endpoint_serial": endpoint_serial,
        "registered_at": clock_now(),
        "reads_received_count": 0,
        "rssi_sum_dbm": 0,
        "status": "REGISTERED",
        "_reads": [],
    })
    db.endpoint_registrations[reg["id"]] = reg
    return ok_object(ser_registration(reg), 201)


@bp.get("/api/endpoint-registrations")
@require_roles(*ALL_ROLES)
def list_registrations():
    filters = {}
    for k in ("work_order_id", "meter_id", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args[k]
    return list_page(db.endpoint_registrations.values(), filters, ser_registration)


@bp.get("/api/endpoint-registrations/<registrationId>")
@require_roles(*ALL_ROLES)
def get_registration(registrationId):
    return ok_object(ser_registration(
        get_or_404(db.endpoint_registrations, registrationId, "EndpointRegistration")))


@bp.post("/api/endpoint-registrations/<registrationId>/verify")
@require_roles("AmiOperator")
def verify_registration(registrationId):
    reg = get_or_404(db.endpoint_registrations, registrationId, "EndpointRegistration")
    if reg["status"] != "REGISTERED":
        raise_err("ERR_INVALID_STATE", "Registration is not REGISTERED")
    # comm_verification (scaffold 1.3): reads within [registered_at,
    # registered_at + 72h], both bounds inclusive; >= 4 reads and exact
    # average rssi >= -95 dBm.
    start = reg["registered_at"]
    end = start + timedelta(hours=COMM_WINDOW_HOURS)
    window_reads = [
        r for r in reg["_reads"] if start <= r["read_at"] <= end
    ]
    count = len(window_reads)
    rssi_sum = sum(r["rssi_dbm"] for r in window_reads)
    # Exact rational comparison: avg >= -95  <=>  sum >= -95 * count.
    passed = count >= AMI_MIN_READS and rssi_sum >= RSSI_MIN_DBM * count
    if passed:
        reg["status"] = "COMM_VERIFIED"
        touch(reg)
        wo = db.work_orders.get(reg["work_order_id"])
        if wo is not None and wo["lifecycle_status"] == "RECONCILED":
            enter_qa_review(wo)
    else:
        reg["status"] = "COMM_FAILED"
        touch(reg)
    return ok_object(ser_registration(reg))


@bp.post("/api/endpoint-registrations/<registrationId>/replace")
@require_roles("AmiOperator")
def replace_registration(registrationId):
    reg = get_or_404(db.endpoint_registrations, registrationId, "EndpointRegistration")
    b = body()
    new_serial = req_str(b, "new_endpoint_serial")
    # Uniqueness (stage 6) precedes the state check (stage 7).
    if _serial_in_use(new_serial):
        raise_err("ERR_AMI_ENDPOINT_SERIAL_CONFLICT",
                  "endpoint_serial already registered")
    if reg["status"] != "COMM_FAILED":
        raise_err("ERR_INVALID_STATE", "Registration is not COMM_FAILED")
    reg["status"] = "REPLACED"
    touch(reg)
    wo = db.work_orders.get(reg["work_order_id"])
    new_reg = base_resource()
    new_reg.update({
        "work_order_id": reg["work_order_id"],
        "meter_id": wo["new_meter_id"] if wo is not None else reg["meter_id"],
        "endpoint_serial": new_serial,
        "registered_at": clock_now(),
        "reads_received_count": 0,
        "rssi_sum_dbm": 0,
        "status": "REGISTERED",
        "_reads": [],
    })
    db.endpoint_registrations[new_reg["id"]] = new_reg
    return ok_object(ser_registration(new_reg), 201)


@bp.post("/api/_ami/ingest-read")
@require_roles("AmiOperator")
def ingest_read():
    b = body()
    registration_id = b.get("endpoint_registration_id")
    if isinstance(registration_id, str):
        get_or_404(db.endpoint_registrations, registration_id,
                   "EndpointRegistration")
    registration_id = req_str(b, "endpoint_registration_id")
    reg = get_or_404(db.endpoint_registrations, registration_id,
                     "EndpointRegistration")
    rssi_dbm = req_int(b, "rssi_dbm")
    read_at = req_dt(b, "read_at")
    reg["reads_received_count"] += 1
    reg["rssi_sum_dbm"] += rssi_dbm
    reg["_reads"].append({"read_at": read_at, "rssi_dbm": rssi_dbm})
    touch(reg)
    return ok_object(ser_registration(reg))
