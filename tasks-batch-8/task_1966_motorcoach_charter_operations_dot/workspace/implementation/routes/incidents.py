"""Incident report endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from services.helpers import (
    get_pagination, paginate, require_fields, get_str, get_enum, get_datetime,
)
from services.safety import compute_incident_impact, recalc_driver_safety_score
from services.serializers import incident_view

bp = Blueprint("incidents", __name__)


INCIDENT_TYPES = ("ACCIDENT", "BREAKDOWN", "TRAFFIC_VIOLATION", "CUSTOMER_COMPLAINT", "HOS_VIOLATION", "CARGO_DAMAGE", "OTHER")
SEVERITIES = ("MINOR", "MODERATE", "MAJOR", "CRITICAL")
RESOLUTION_STATUSES = ("OPEN", "UNDER_INVESTIGATION", "RESOLVED", "CLOSED")


@bp.route("/api/v1/orders/<oid>/incidents", methods=["POST"])
def create_incident(oid):
    require_roles("DispatchManager", "SafetyOfficer", "PlatformAdmin")
    o = db.orders.get(oid)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")

    payload = request.get_json(silent=True) or {}
    require_fields(payload, "driver_id", "vehicle_id", "incident_type", "severity", "description", "occurred_at", "reported_by")
    driver_id = get_str(payload, "driver_id", required=True)
    vehicle_id = get_str(payload, "vehicle_id", required=True)
    incident_type = get_enum(payload, "incident_type", INCIDENT_TYPES, required=True)
    severity = get_enum(payload, "severity", SEVERITIES, required=True)
    description = get_str(payload, "description", required=True)
    occurred_at = get_datetime(payload, "occurred_at", required=True)
    reported_by = get_str(payload, "reported_by", required=True)

    if db.drivers.get(driver_id) is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "driver not found")
    if db.vehicles.get(vehicle_id) is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "vehicle not found")

    dot_recordable = (incident_type == "ACCIDENT" and severity in ("MAJOR", "CRITICAL"))
    safety_score_impact = compute_incident_impact(incident_type, severity)

    iid = db.new_id()
    i = {
        "id": iid,
        "order_id": oid,
        "driver_id": driver_id,
        "vehicle_id": vehicle_id,
        "incident_type": incident_type,
        "severity": severity,
        "description": description,
        "occurred_at": db.to_iso(occurred_at),
        "reported_by": reported_by,
        "dot_recordable": dot_recordable,
        "resolution_status": "OPEN",
        "resolution_notes": None,
        "safety_score_impact": safety_score_impact,
        "created_at": db.iso_now(),
    }
    db.incidents[iid] = i

    recalc_driver_safety_score(driver_id)

    return success_object(incident_view(i), status=201)


@bp.route("/api/v1/orders/<oid>/incidents", methods=["GET"])
def list_incidents(oid):
    require_roles("DispatchManager", "SafetyOfficer", "PlatformAdmin")
    o = db.orders.get(oid)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")
    limit, offset = get_pagination()
    incident_type = request.args.get("incident_type")
    severity = request.args.get("severity")
    items = sorted([i for i in db.incidents.values() if i.get("order_id") == oid], key=lambda x: x["created_at"])
    if incident_type:
        items = [i for i in items if i.get("incident_type") == incident_type]
    if severity:
        items = [i for i in items if i.get("severity") == severity]
    page, total = paginate(items, limit, offset)
    return success_list([incident_view(i) for i in page], limit, offset, total)


@bp.route("/api/v1/incidents/<iid>", methods=["PATCH"])
def update_incident(iid):
    require_roles("SafetyOfficer")
    i = db.incidents.get(iid)
    if i is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "incident not found")
    payload = request.get_json(silent=True) or {}
    if "resolution_status" in payload:
        rs = get_enum(payload, "resolution_status", RESOLUTION_STATUSES, required=True)
        i["resolution_status"] = rs
    if "resolution_notes" in payload:
        i["resolution_notes"] = get_str(payload, "resolution_notes", required=True)
    return success_object(incident_view(i))
