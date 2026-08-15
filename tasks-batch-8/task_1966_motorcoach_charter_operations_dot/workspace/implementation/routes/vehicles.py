"""Vehicle endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from services.helpers import (
    get_pagination, paginate, touch, require_fields, get_str, get_bool, get_int, get_enum, get_datetime,
)
from services.serializers import vehicle_view, order_view, incident_view, breakdown_view

bp = Blueprint("vehicles", __name__)


VEHICLE_CLASSES = ("STANDARD", "PREMIUM", "EXECUTIVE")


@bp.route("/api/v1/vehicles", methods=["POST"])
def create_vehicle():
    require_roles("FleetManager", "PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    require_fields(
        payload,
        "unit_number", "make_model", "year", "seating_capacity",
        "dot_inspection_expiry", "maintenance_due_miles",
        "insurance_policy_number", "insurance_expiry",
    )
    unit_number = get_str(payload, "unit_number", required=True)
    make_model = get_str(payload, "make_model", required=True)
    year = get_int(payload, "year", required=True)
    seating_capacity = get_int(payload, "seating_capacity", required=True)
    ada_accessible = get_bool(payload, "ada_accessible", default=False)
    vehicle_class = get_enum(payload, "vehicle_class_requested", VEHICLE_CLASSES, default="STANDARD") if "vehicle_class_requested" in payload else get_enum(payload, "vehicle_class", VEHICLE_CLASSES, default="STANDARD")
    dot_inspection_expiry = get_datetime(payload, "dot_inspection_expiry", required=True)
    maintenance_due_miles = get_int(payload, "maintenance_due_miles", required=True)
    insurance_policy_number = get_str(payload, "insurance_policy_number", required=True)
    insurance_expiry = get_datetime(payload, "insurance_expiry", required=True)

    for v in db.vehicles.values():
        if v["unit_number"] == unit_number:
            raise errors.make_error(errors.ERR_INVALID_REQUEST, "unit_number must be unique")

    now = db.iso_now()
    vid = db.new_id()
    v = {
        "id": vid,
        "unit_number": unit_number,
        "make_model": make_model,
        "year": year,
        "seating_capacity": seating_capacity,
        "ada_accessible": ada_accessible,
        "vehicle_class": vehicle_class,
        "status": "AVAILABLE",
        "dot_inspection_expiry": db.to_iso(dot_inspection_expiry),
        "last_inspection_date": None,
        "odometer_miles": 0,
        "maintenance_due_miles": maintenance_due_miles,
        "insurance_policy_number": insurance_policy_number,
        "insurance_expiry": db.to_iso(insurance_expiry),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.vehicles[vid] = v
    return success_object(vehicle_view(v), status=201)


@bp.route("/api/v1/vehicles", methods=["GET"])
def list_vehicles():
    require_roles("FleetManager", "DispatchManager", "PlatformAdmin")
    limit, offset = get_pagination()
    status = request.args.get("status")
    vehicle_class = request.args.get("vehicle_class")
    items = sorted(db.vehicles.values(), key=lambda x: x["created_at"])
    if status:
        items = [v for v in items if v.get("status") == status]
    if vehicle_class:
        items = [v for v in items if v.get("vehicle_class") == vehicle_class]
    page, total = paginate(items, limit, offset)
    return success_list([vehicle_view(v) for v in page], limit, offset, total)


@bp.route("/api/v1/vehicles/<vid>", methods=["GET"])
def get_vehicle(vid):
    require_roles("FleetManager", "DispatchManager", "PlatformAdmin")
    v = db.vehicles.get(vid)
    if v is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "vehicle not found")
    return success_object(vehicle_view(v))


@bp.route("/api/v1/vehicles/<vid>/send-to-maintenance", methods=["POST"])
def send_to_maintenance(vid):
    require_roles("FleetManager")
    v = db.vehicles.get(vid)
    if v is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "vehicle not found")
    if v["status"] != "AVAILABLE":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"vehicle is in state {v['status']}, cannot send to maintenance")
    v["status"] = "IN_MAINTENANCE"
    touch(v)
    return success_object(vehicle_view(v))


@bp.route("/api/v1/vehicles/<vid>/decommission", methods=["POST"])
def decommission(vid):
    require_roles("FleetManager")
    v = db.vehicles.get(vid)
    if v is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "vehicle not found")
    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason")
    if not reason or not isinstance(reason, str):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "reason is required")
    if v["status"] not in ("AVAILABLE", "IN_MAINTENANCE"):
        raise errors.make_error(errors.ERR_INVALID_STATE, f"vehicle is in state {v['status']}, cannot decommission")
    v["status"] = "OUT_OF_SERVICE"
    touch(v)
    return success_object(vehicle_view(v))


@bp.route("/api/v1/vehicles/<vid>/orders", methods=["GET"])
def list_vehicle_orders(vid):
    require_roles("FleetManager", "DispatchManager", "PlatformAdmin")
    v = db.vehicles.get(vid)
    if v is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "vehicle not found")
    limit, offset = get_pagination()
    items = sorted([o for o in db.orders.values() if o.get("assigned_vehicle_id") == vid], key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([order_view(o) for o in page], limit, offset, total)


@bp.route("/api/v1/vehicles/<vid>/incidents", methods=["GET"])
def list_vehicle_incidents(vid):
    require_roles("FleetManager", "DispatchManager", "SafetyOfficer", "PlatformAdmin")
    v = db.vehicles.get(vid)
    if v is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "vehicle not found")
    limit, offset = get_pagination()
    items = sorted([i for i in db.incidents.values() if i.get("vehicle_id") == vid], key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([incident_view(i) for i in page], limit, offset, total)


@bp.route("/api/v1/vehicles/<vid>/breakdowns", methods=["GET"])
def list_vehicle_breakdowns(vid):
    require_roles("FleetManager", "DispatchManager", "PlatformAdmin")
    v = db.vehicles.get(vid)
    if v is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "vehicle not found")
    limit, offset = get_pagination()
    items = sorted([b for b in db.breakdowns.values() if b.get("vehicle_id") == vid or b.get("replacement_vehicle_id") == vid], key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([breakdown_view(b) for b in page], limit, offset, total)
