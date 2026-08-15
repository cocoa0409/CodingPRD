"""Maintenance record endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from services.helpers import (
    get_pagination, paginate, require_fields, get_str, get_enum, get_datetime, get_int, get_bool, get_list, touch,
)
from services.pricing import MAINTENANCE_INTERVAL_MILES
from services.safety import recalc_customer_safety_audit_score
from services.serializers import maintenance_record_view

bp = Blueprint("maintenance", __name__)


MAINTENANCE_TYPES = ("PREVENTIVE", "DOT_INSPECTION", "REPAIR", "RECALL", "TIRE_REPLACE", "BRAKE_SERVICE")


def lazy_overdue_check(m: dict):
    if m.get("status") == "SCHEDULED" and m.get("scheduled_date"):
        sd = db.parse_iso(m["scheduled_date"])
        if db.now_utc() > sd:
            m["status"] = "OVERDUE"


@bp.route("/api/v1/vehicles/<vid>/maintenance-records", methods=["POST"])
def create_maintenance_record(vid):
    require_roles("FleetManager")
    v = db.vehicles.get(vid)
    if v is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "vehicle not found")

    payload = request.get_json(silent=True) or {}
    require_fields(payload, "maintenance_type", "scheduled_date", "description", "technician", "cost_cents", "odometer_at_service")
    maintenance_type = get_enum(payload, "maintenance_type", MAINTENANCE_TYPES, required=True)
    scheduled_date = get_datetime(payload, "scheduled_date", required=True)
    description = get_str(payload, "description", required=True)
    technician = get_str(payload, "technician", required=True)
    cost_cents = get_int(payload, "cost_cents", required=True)
    odometer_at_service = get_int(payload, "odometer_at_service", required=True)
    dot_inspection_passed = get_bool(payload, "dot_inspection_passed", default=None)
    defects_found = get_list(payload, "defects_found", default=[]) or []

    mid = db.new_id()
    m = {
        "id": mid,
        "vehicle_id": vid,
        "maintenance_type": maintenance_type,
        "status": "SCHEDULED",
        "scheduled_date": db.to_iso(scheduled_date),
        "completed_date": None,
        "odometer_at_service": odometer_at_service,
        "description": description,
        "technician": technician,
        "cost_cents": cost_cents,
        "next_due_miles": None,
        "dot_inspection_passed": dot_inspection_passed,
        "defects_found": defects_found,
        "created_at": db.iso_now(),
    }
    db.maintenance_records[mid] = m
    return success_object(maintenance_record_view(m), status=201)


@bp.route("/api/v1/vehicles/<vid>/maintenance-records", methods=["GET"])
def list_maintenance_records(vid):
    require_roles("FleetManager", "DispatchManager", "SafetyOfficer")
    v = db.vehicles.get(vid)
    if v is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "vehicle not found")
    limit, offset = get_pagination()
    maintenance_type = request.args.get("maintenance_type")
    status = request.args.get("status")
    items = sorted([m for m in db.maintenance_records.values() if m.get("vehicle_id") == vid], key=lambda x: x["created_at"])
    for m in items:
        lazy_overdue_check(m)
    if maintenance_type:
        items = [m for m in items if m.get("maintenance_type") == maintenance_type]
    if status:
        items = [m for m in items if m.get("status") == status]
    page, total = paginate(items, limit, offset)
    return success_list([maintenance_record_view(m) for m in page], limit, offset, total)


@bp.route("/api/v1/maintenance-records/<mid>/start", methods=["POST"])
def start_maintenance(mid):
    require_roles("FleetManager")
    m = db.maintenance_records.get(mid)
    if m is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "maintenance record not found")
    if m["status"] != "SCHEDULED":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"maintenance record is in state {m['status']}, cannot start")
    v = db.vehicles.get(m["vehicle_id"])
    if v is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "vehicle not found")
    if v["status"] != "IN_MAINTENANCE":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"vehicle is in state {v['status']}, must be IN_MAINTENANCE")
    m["status"] = "IN_PROGRESS"
    return success_object(maintenance_record_view(m))


@bp.route("/api/v1/maintenance-records/<mid>/complete", methods=["POST"])
def complete_maintenance(mid):
    require_roles("FleetManager")
    m = db.maintenance_records.get(mid)
    if m is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "maintenance record not found")
    if m["status"] != "IN_PROGRESS":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"maintenance record is in state {m['status']}, cannot complete")

    v = db.vehicles.get(m["vehicle_id"])
    if v is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "vehicle not found")

    payload = request.get_json(silent=True) or {}
    odometer_at_service = payload.get("odometer_at_service")
    if odometer_at_service is None:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "odometer_at_service is required")
    if isinstance(odometer_at_service, bool) or not isinstance(odometer_at_service, int):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "odometer_at_service must be an integer")
    if odometer_at_service < v.get("odometer_miles", 0):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "odometer_at_service must be >= vehicle odometer")

    if m["maintenance_type"] == "DOT_INSPECTION":
        if "dot_inspection_passed" not in payload or payload.get("dot_inspection_passed") is None:
            raise errors.make_error(errors.ERR_INVALID_REQUEST, "dot_inspection_passed is required for DOT_INSPECTION")
        if not isinstance(payload["dot_inspection_passed"], bool):
            raise errors.make_error(errors.ERR_INVALID_REQUEST, "dot_inspection_passed must be a boolean")
        m["dot_inspection_passed"] = payload["dot_inspection_passed"]

    m["odometer_at_service"] = odometer_at_service
    m["completed_date"] = db.iso_now()
    m["next_due_miles"] = odometer_at_service + MAINTENANCE_INTERVAL_MILES
    m["status"] = "COMPLETED"

    # Vehicle transition
    if v["status"] == "IN_MAINTENANCE":
        v["status"] = "AVAILABLE"
    v["maintenance_due_miles"] = m["next_due_miles"]
    if m["maintenance_type"] == "DOT_INSPECTION" and m.get("dot_inspection_passed"):
        v["last_inspection_date"] = m["completed_date"]
    touch(v)

    # Recalculate safety audit scores for customers with orders on this vehicle
    affected_customers = set()
    for o in db.orders.values():
        if o.get("assigned_vehicle_id") == v["id"]:
            affected_customers.add(o.get("customer_id"))
    for cid in affected_customers:
        if cid:
            recalc_customer_safety_audit_score(cid)
            cust = db.customers.get(cid)
            if cust:
                touch(cust)

    return success_object(maintenance_record_view(m))
