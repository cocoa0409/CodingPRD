"""Meter reading endpoints (PRD 3.5): append-only event log."""
import db
from db import clock_now, new_id, next_seq
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.core import get_or_404, list_page, ser_reading
from flask import Blueprint, request
from validate import body, req_dt, req_enum, req_int, req_str

bp = Blueprint("readings", __name__)

READ_TYPES = ("FINAL", "INITIAL", "VERIFICATION", "ESTIMATED")
SOURCES = ("FIELD_CREW", "AMI_NETWORK", "CUSTOMER", "SYSTEM_ESTIMATE")


@bp.post("/api/readings")
@require_roles("FieldContractor", "Scheduler")
def create_reading():
    b = body()
    work_order_id = b.get("work_order_id")
    if isinstance(work_order_id, str):
        get_or_404(db.work_orders, work_order_id, "WorkOrder")
    work_order_id = req_str(b, "work_order_id")
    get_or_404(db.work_orders, work_order_id, "WorkOrder")
    meter_id = b.get("meter_id")
    if isinstance(meter_id, str):
        get_or_404(db.meters, meter_id, "Meter")
    meter_id = req_str(b, "meter_id")
    get_or_404(db.meters, meter_id, "Meter")
    read_type = req_enum(b, "read_type", READ_TYPES)
    value = req_int(b, "value", min=0)
    source = req_enum(b, "source", SOURCES)
    read_at = req_dt(b, "read_at")
    r = {
        "id": new_id(),
        "created_at": clock_now(),
        "_seq": next_seq(),
        "work_order_id": work_order_id,
        "meter_id": meter_id,
        "read_type": read_type,
        "value": value,
        "source": source,
        "read_at": read_at,
    }
    db.readings[r["id"]] = r
    return ok_object(ser_reading(r), 201)


@bp.get("/api/readings")
@require_roles(*ALL_ROLES)
def list_readings():
    filters = {}
    for k in ("work_order_id", "meter_id", "read_type"):
        if request.args.get(k) is not None:
            filters[k] = request.args[k]
    return list_page(db.readings.values(), filters, ser_reading)


@bp.get("/api/readings/<readingId>")
@require_roles(*ALL_ROLES)
def get_reading(readingId):
    return ok_object(ser_reading(get_or_404(db.readings, readingId, "MeterReading")))
