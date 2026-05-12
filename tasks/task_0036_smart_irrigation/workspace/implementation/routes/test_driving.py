"""Test-driving endpoints (no auth required)."""

from datetime import timedelta

from flask import Blueprint

from clock import CLOCK, parse_iso
from db import DB
from errors import validation_error
from response import success_object
from services.alerts import emit_alert
from services.common import (
    bump_version,
    get_json_body,
    to_aware_utc,
)
from services.plans import auto_complete_plans


bp = Blueprint("test_driving", __name__)


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    body = get_json_body()
    target = body.get("to_iso8601")
    if not isinstance(target, str) or not target.strip():
        raise validation_error("to_iso8601 is required")
    try:
        target_dt = parse_iso(target)
    except Exception:
        raise validation_error("to_iso8601 must be ISO 8601")
    CLOCK.advance_to(target_dt)
    # Re-evaluate time-gated transitions
    auto_complete_plans(CLOCK.now())
    return success_object({}, status=200)


@bp.route("/_sweep/run", methods=["POST"])
def sweep_run():
    """Archive sensor readings older than 24h or with validity ABNORMAL_FILTERED."""
    now = to_aware_utc(CLOCK.now())
    cutoff = now - timedelta(hours=24)
    for r in DB.sensor_readings.values():
        if r.get("archived"):
            continue
        ts = to_aware_utc(r.get("reading_timestamp"))
        if r.get("validity") == "ABNORMAL_FILTERED" or (ts is not None and ts < cutoff):
            r["archived"] = True
    return success_object({}, status=200)


@bp.route("/_events/emit", methods=["POST"])
def events_emit():
    body = get_json_body()
    event_type = body.get("event_type")
    payload = body.get("payload") or {}
    if not isinstance(event_type, str) or not event_type:
        raise validation_error("event_type is required")
    if not isinstance(payload, dict):
        raise validation_error("payload must be an object")

    if event_type == "WEATHER_RAINFALL":
        plot_id = payload.get("plot_id")
        rainfall_mm = payload.get("rainfall_mm")
        if not isinstance(plot_id, str):
            raise validation_error("payload.plot_id required")
        if isinstance(rainfall_mm, bool) or not isinstance(rainfall_mm, (int, float)):
            raise validation_error("payload.rainfall_mm must be a number")
        DB.cached_rainfall_mm[plot_id] = float(rainfall_mm)
    elif event_type == "DEVICE_OFFLINE":
        sensor_id = payload.get("sensor_id")
        if not isinstance(sensor_id, str):
            raise validation_error("payload.sensor_id required")
        sensor = DB.sensors.get(sensor_id)
        if sensor is not None:
            sensor["status"] = "OFFLINE"
            bump_version(sensor)
            plot = DB.plots.get(sensor["plot_id"])
            tenant_id = plot.get("tenant_id") if plot else None
            emit_alert(
                rule_code="SENSOR_OFFLINE",
                subject_type="SENSOR",
                subject_id=sensor_id,
                tenant_id=tenant_id,
            )
    elif event_type == "PAYMENT_CONFIRMED":
        bill_id = payload.get("bill_id")
        amount_cents = payload.get("amount_cents")
        if not isinstance(bill_id, str):
            raise validation_error("payload.bill_id required")
        if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
            raise validation_error("payload.amount_cents must be an integer")
        bill = DB.water_bills.get(bill_id)
        if bill is not None and bill.get("status") in ("ISSUED", "DISPUTED"):
            bill["amount_paid_cents"] = int(bill.get("amount_paid_cents", 0)) + int(amount_cents)
            if bill["amount_paid_cents"] >= int(bill.get("total_amount_cents", 0)):
                bill["status"] = "PAID"
            bump_version(bill)
    return success_object({}, status=200)
