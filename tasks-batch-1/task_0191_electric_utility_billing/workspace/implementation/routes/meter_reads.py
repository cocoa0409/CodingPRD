"""MeterRead (AMI import) endpoints (PRD §3.2)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, base_record
from errors import err
from middleware import authenticate, require_roles
from response import success
from services import serializers as ser
from services.common import (
    get_json_body,
    paginate,
    parse_dt,
    parse_pagination,
    require_dt,
    require_fields,
    require_number,
)
from services.pricing import tou_period_for_hour

bp = Blueprint("meter_reads", __name__)

READ_ROLES = {"BillingOperator", "Customer"}


@bp.route("/meter-reads", methods=["POST"])
def create_meter_read():
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    body = get_json_body()
    require_fields(body, ["meter_id", "interval_start", "interval_end", "import_kwh"])

    meter_id = body["meter_id"]
    start_dt = require_dt(body, "interval_start")
    end_dt = require_dt(body, "interval_end")
    import_kwh = require_number(body, "import_kwh")
    export_kwh = body.get("export_kwh", 0)
    if export_kwh is None:
        export_kwh = 0
    if isinstance(export_kwh, bool) or not isinstance(export_kwh, (int, float)):
        raise err("ERR_INVALID_REQUEST", "export_kwh must be a number.")

    meter = db.meters.get(meter_id)
    if meter is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced meter does not exist.")

    # Range checks (priority 19): non-negative kWh.
    if import_kwh < 0 or export_kwh < 0:
        raise err("ERR_VALIDATION_RANGE", "import_kwh and export_kwh must be >= 0.")

    # Interval shape (priority 7): exactly 60 minutes; no export on CONSUMPTION_ONLY.
    if end_dt != start_dt + timedelta(minutes=60):
        raise err("ERR_INVALID_INTERVAL", "interval_end must equal interval_start + 60min.")
    if meter["meter_type"] == "CONSUMPTION_ONLY" and export_kwh > 0:
        raise err(
            "ERR_INVALID_INTERVAL",
            "export_kwh must be 0 for a CONSUMPTION_ONLY meter.",
        )

    # Overlap (priority 16): no overlapping read for the same meter.
    for r in db.meter_reads.values():
        if r["meter_id"] != meter_id:
            continue
        r_start = parse_dt(r["interval_start"])
        r_end = parse_dt(r["interval_end"])
        if r_start is None or r_end is None:
            continue
        # half-open intervals overlap iff start < r_end and r_start < end
        if start_dt < r_end and r_start < end_dt:
            raise err("ERR_READ_OVERLAP", "Read interval overlaps an existing read.")

    tou_period = tou_period_for_hour(start_dt.hour)
    avg_demand_kw = import_kwh  # interval is exactly one hour -> kWh == avg kW

    rec = base_record(common_fields=False)
    rec.update({
        "meter_id": meter_id,
        "interval_start": body["interval_start"],
        "interval_end": body["interval_end"],
        "import_kwh": import_kwh,
        "export_kwh": export_kwh,
        "tou_period": tou_period,
        "avg_demand_kw": avg_demand_kw,
    })
    db.meter_reads[rec["id"]] = rec
    return success(ser.meter_read(rec), status=201)


@bp.route("/meter-reads/<read_id>", methods=["GET"])
def get_meter_read(read_id):
    user_id, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.meter_reads.get(read_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Meter read not found.")
    if role == "Customer":
        meter = db.meters.get(rec["meter_id"])
        owning = meter["account_id"] if meter else None
        if owning != user_id:
            raise err("ERR_FORBIDDEN_ROLE", "Customer may only read own reads.")
    return success(ser.meter_read(rec), status=200)


@bp.route("/meter-reads", methods=["GET"])
def list_meter_reads():
    user_id, role = authenticate()
    require_roles(role, READ_ROLES)
    parse_pagination()
    meter_id = request.args.get("meter_id")
    items = list(db.meter_reads.values())
    if meter_id is not None:
        items = [r for r in items if r["meter_id"] == meter_id]
    if role == "Customer":
        owned_meter_ids = {
            m["id"] for m in db.meters.values() if m["account_id"] == user_id
        }
        items = [r for r in items if r["meter_id"] in owned_meter_ids]
    page, pagination = paginate(items)
    return success([ser.meter_read(r) for r in page], status=200, pagination=pagination)
