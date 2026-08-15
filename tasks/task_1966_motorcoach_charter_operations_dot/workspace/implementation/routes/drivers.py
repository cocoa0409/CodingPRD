"""Driver endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from services.helpers import (
    get_pagination, paginate, touch, require_fields, get_str, get_enum, get_datetime, get_list,
)
from services.serializers import driver_view, order_view, trip_log_view, incident_view, breakdown_view

bp = Blueprint("drivers", __name__)


CDL_CLASSES = ("CLASS_A", "CLASS_B", "CLASS_C")
HOS_CYCLES = ("CYCLE_70_8", "CYCLE_60_7")


def lazy_rest_check(d: dict):
    """OFF_DUTY -> AVAILABLE after 10h rest."""
    if d.get("status") == "OFF_DUTY" and d.get("last_rest_start"):
        rest_start = db.parse_iso(d["last_rest_start"])
        if db.now_utc() >= rest_start + timedelta(hours=10):
            d["status"] = "AVAILABLE"
            d["current_driving_hours_today"] = 0.0
            d["current_on_duty_hours_today"] = 0.0
            d["consecutive_driving_minutes"] = 0
            touch(d)


@bp.route("/api/v1/drivers", methods=["POST"])
def create_driver():
    require_roles("FleetManager", "PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, "full_name", "cdl_number", "cdl_class", "endorsements", "hire_date")
    full_name = get_str(payload, "full_name", required=True)
    cdl_number = get_str(payload, "cdl_number", required=True)
    cdl_class = get_enum(payload, "cdl_class", CDL_CLASSES, required=True)
    endorsements = get_list(payload, "endorsements", required=True)
    hire_date = get_datetime(payload, "hire_date", required=True)
    hos_cycle_type = get_enum(payload, "hos_cycle_type", HOS_CYCLES, default="CYCLE_70_8")

    for d in db.drivers.values():
        if d["cdl_number"] == cdl_number:
            raise errors.make_error(errors.ERR_INVALID_REQUEST, "cdl_number must be unique")

    now = db.iso_now()
    did = db.new_id()
    d = {
        "id": did,
        "full_name": full_name,
        "cdl_number": cdl_number,
        "cdl_class": cdl_class,
        "endorsements": endorsements,
        "hire_date": db.to_iso(hire_date),
        "status": "AVAILABLE",
        "hos_cycle_type": hos_cycle_type,
        "current_driving_hours_today": 0.0,
        "current_on_duty_hours_today": 0.0,
        "current_cycle_hours": 0.0,
        "last_rest_start": None,
        "consecutive_driving_minutes": 0,
        "safety_score": 100.0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.drivers[did] = d
    return success_object(driver_view(d), status=201)


@bp.route("/api/v1/drivers", methods=["GET"])
def list_drivers():
    require_roles("FleetManager", "DispatchManager", "SafetyOfficer", "PlatformAdmin")
    limit, offset = get_pagination()
    status = request.args.get("status")
    items = sorted(db.drivers.values(), key=lambda x: x["created_at"])
    for d in items:
        lazy_rest_check(d)
    if status:
        items = [d for d in items if d.get("status") == status]
    page, total = paginate(items, limit, offset)
    return success_list([driver_view(d) for d in page], limit, offset, total)


@bp.route("/api/v1/drivers/<did>", methods=["GET"])
def get_driver(did):
    require_roles("FleetManager", "DispatchManager", "SafetyOfficer", "PlatformAdmin")
    d = db.drivers.get(did)
    if d is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "driver not found")
    lazy_rest_check(d)
    return success_object(driver_view(d))


@bp.route("/api/v1/drivers/<did>/suspend", methods=["POST"])
def suspend_driver(did):
    require_roles("SafetyOfficer")
    d = db.drivers.get(did)
    if d is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "driver not found")
    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason")
    if not reason or not isinstance(reason, str):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "reason is required")
    if d["status"] == "AVAILABLE":
        pass
    elif d["status"] == "ON_DUTY_NOT_DRIVING":
        for o in db.orders.values():
            if o.get("assigned_driver_id") == did and o.get("status") in ("ASSIGNED", "IN_PROGRESS"):
                raise errors.make_error(errors.ERR_INVALID_STATE, "driver has active orders")
    else:
        raise errors.make_error(errors.ERR_INVALID_STATE, f"driver is in state {d['status']}, cannot suspend")
    d["status"] = "SUSPENDED"
    touch(d)
    return success_object(driver_view(d))


@bp.route("/api/v1/drivers/<did>/reinstate", methods=["POST"])
def reinstate_driver(did):
    require_roles("SafetyOfficer")
    d = db.drivers.get(did)
    if d is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "driver not found")
    if d["status"] != "SUSPENDED":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"driver is in state {d['status']}, cannot reinstate")
    if float(d.get("safety_score", 100.0)) < 30.0:
        raise errors.make_error(errors.ERR_REINSTATEMENT_DENIED, "driver safety score too low for reinstatement")
    d["status"] = "AVAILABLE"
    touch(d)
    return success_object(driver_view(d))


@bp.route("/api/v1/drivers/<did>/check-rest", methods=["POST"])
def check_rest(did):
    require_roles("FleetManager", "DispatchManager")
    d = db.drivers.get(did)
    if d is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "driver not found")
    lazy_rest_check(d)
    return success_object(driver_view(d))


@bp.route("/api/v1/drivers/<did>/orders", methods=["GET"])
def list_driver_orders(did):
    require_roles("FleetManager", "DispatchManager", "SafetyOfficer", "PlatformAdmin")
    d = db.drivers.get(did)
    if d is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "driver not found")
    limit, offset = get_pagination()
    items = sorted(
        [o for o in db.orders.values() if o.get("assigned_driver_id") == did or o.get("relief_driver_id") == did],
        key=lambda x: x["created_at"],
    )
    page, total = paginate(items, limit, offset)
    return success_list([order_view(o) for o in page], limit, offset, total)


@bp.route("/api/v1/drivers/<did>/trip-logs", methods=["GET"])
def list_driver_trip_logs(did):
    require_roles("FleetManager", "DispatchManager", "SafetyOfficer", "PlatformAdmin")
    d = db.drivers.get(did)
    if d is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "driver not found")
    limit, offset = get_pagination()
    items = sorted([t for t in db.trip_logs.values() if t.get("driver_id") == did], key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([trip_log_view(t) for t in page], limit, offset, total)


@bp.route("/api/v1/drivers/<did>/incidents", methods=["GET"])
def list_driver_incidents(did):
    require_roles("FleetManager", "DispatchManager", "SafetyOfficer", "PlatformAdmin")
    d = db.drivers.get(did)
    if d is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "driver not found")
    limit, offset = get_pagination()
    items = sorted([i for i in db.incidents.values() if i.get("driver_id") == did], key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([incident_view(i) for i in page], limit, offset, total)


@bp.route("/api/v1/drivers/<did>/breakdowns", methods=["GET"])
def list_driver_breakdowns(did):
    require_roles("FleetManager", "DispatchManager", "PlatformAdmin")
    d = db.drivers.get(did)
    if d is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "driver not found")
    limit, offset = get_pagination()
    items = sorted(
        [b for b in db.breakdowns.values() if b.get("driver_id") == did or b.get("replacement_driver_id") == did],
        key=lambda x: x["created_at"],
    )
    page, total = paginate(items, limit, offset)
    return success_list([breakdown_view(b) for b in page], limit, offset, total)
