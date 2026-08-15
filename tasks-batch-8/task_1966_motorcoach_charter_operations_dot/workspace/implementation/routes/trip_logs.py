"""Trip log endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from services.helpers import (
    get_pagination, paginate, require_fields, get_str, get_enum, get_datetime, get_int, touch,
)
from services.serializers import trip_log_view

bp = Blueprint("trip_logs", __name__)


LOG_TYPES = ("DRIVING", "ON_DUTY_NOT_DRIVING", "OFF_DUTY", "SLEEPER_BERTH")


@bp.route("/api/v1/orders/<oid>/trip-logs", methods=["POST"])
def create_trip_log(oid):
    require_roles("DispatchManager", "PlatformAdmin")
    o = db.orders.get(oid)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")

    payload = request.get_json(silent=True) or {}
    require_fields(payload, "driver_id", "log_type", "start_time", "end_time", "start_location", "end_location")
    driver_id = get_str(payload, "driver_id", required=True)
    log_type = get_enum(payload, "log_type", LOG_TYPES, required=True)
    start_time = get_datetime(payload, "start_time", required=True)
    end_time = get_datetime(payload, "end_time", required=True)
    start_location = get_str(payload, "start_location", required=True)
    end_location = get_str(payload, "end_location", required=True)
    miles_driven = get_int(payload, "miles_driven", default=0) or 0

    driver = db.drivers.get(driver_id)
    if driver is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "driver not found")

    # Compute duration
    duration_hours = (end_time - start_time).total_seconds() / 3600.0
    duration_minutes = int((end_time - start_time).total_seconds() / 60)

    # Tentatively update accumulators to determine violation
    hos_violation = False
    violation_details = ""
    if log_type == "DRIVING":
        new_driving = float(driver.get("current_driving_hours_today", 0.0)) + duration_hours
        new_on_duty = float(driver.get("current_on_duty_hours_today", 0.0)) + duration_hours
        new_cycle = float(driver.get("current_cycle_hours", 0.0)) + duration_hours
        new_consecutive = int(driver.get("consecutive_driving_minutes", 0)) + duration_minutes
        if new_driving > 11.0:
            hos_violation = True
            violation_details = "Driving hours exceeded 11-hour limit"
        elif new_on_duty > 14.0:
            hos_violation = True
            violation_details = "On-duty hours exceeded 14-hour window"
        else:
            cycle_limit = 70.0 if driver.get("hos_cycle_type") == "CYCLE_70_8" else 60.0
            if new_cycle > cycle_limit:
                hos_violation = True
                violation_details = "Cycle hours exceeded limit"
        # Apply updates
        driver["current_driving_hours_today"] = new_driving
        driver["current_on_duty_hours_today"] = new_on_duty
        driver["current_cycle_hours"] = new_cycle
        driver["consecutive_driving_minutes"] = new_consecutive
    elif log_type == "ON_DUTY_NOT_DRIVING":
        new_on_duty = float(driver.get("current_on_duty_hours_today", 0.0)) + duration_hours
        new_cycle = float(driver.get("current_cycle_hours", 0.0)) + duration_hours
        if new_on_duty > 14.0:
            hos_violation = True
            violation_details = "On-duty hours exceeded 14-hour window"
        else:
            cycle_limit = 70.0 if driver.get("hos_cycle_type") == "CYCLE_70_8" else 60.0
            if new_cycle > cycle_limit:
                hos_violation = True
                violation_details = "Cycle hours exceeded limit"
        driver["current_on_duty_hours_today"] = new_on_duty
        driver["current_cycle_hours"] = new_cycle
    elif log_type in ("OFF_DUTY", "SLEEPER_BERTH"):
        # reset consecutive driving if break >= 30 min
        if duration_minutes >= 30:
            driver["consecutive_driving_minutes"] = 0
    touch(driver)

    tid = db.new_id()
    t = {
        "id": tid,
        "order_id": oid,
        "driver_id": driver_id,
        "log_type": log_type,
        "start_time": db.to_iso(start_time),
        "end_time": db.to_iso(end_time),
        "start_location": start_location,
        "end_location": end_location,
        "miles_driven": miles_driven,
        "hos_violation": hos_violation,
        "violation_details": violation_details,
        "created_at": db.iso_now(),
    }
    db.trip_logs[tid] = t
    return success_object(trip_log_view(t), status=201)


@bp.route("/api/v1/orders/<oid>/trip-logs", methods=["GET"])
def list_trip_logs(oid):
    require_roles("DispatchManager", "SafetyOfficer", "PlatformAdmin")
    o = db.orders.get(oid)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")
    limit, offset = get_pagination()
    driver_id = request.args.get("driver_id")
    log_type = request.args.get("log_type")
    items = sorted([t for t in db.trip_logs.values() if t.get("order_id") == oid], key=lambda x: x["created_at"])
    if driver_id:
        items = [t for t in items if t.get("driver_id") == driver_id]
    if log_type:
        items = [t for t in items if t.get("log_type") == log_type]
    page, total = paginate(items, limit, offset)
    return success_list([trip_log_view(t) for t in page], limit, offset, total)
