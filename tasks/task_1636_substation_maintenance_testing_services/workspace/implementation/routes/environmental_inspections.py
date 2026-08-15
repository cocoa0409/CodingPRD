"""EnvironmentalInspection endpoints."""
from flask import Blueprint, request

import db
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from errors import err_validation, err_state_transition
from services.common import (
    body, require_string, require_number, require_enum, parse_datetime_field,
    parse_pagination, paginate, get_substation, get_environmental_inspection,
)
from services.calculations import compute_containment, compute_compliance, _add_months
from db import _parse_iso

bp = Blueprint("environmental_inspections", __name__)

METHODS = {"SPCC_SIMPLE", "SPCC_WITH_FREEBOARD"}


def inspection_view(e):
    return {
        "id": e["id"],
        "substation_id": e["substation_id"],
        "inspection_date": e["inspection_date"],
        "largest_vessel_gal": e["largest_vessel_gal"],
        "containment_capacity_gal": e["containment_capacity_gal"],
        "rainfall_freeboard_gal": e["rainfall_freeboard_gal"],
        "method": e["method"],
        "required_capacity_gal": e.get("required_capacity_gal"),
        "compliance": e.get("compliance"),
        "status": e["status"],
        "remediation_note": e.get("remediation_note"),
        "next_inspection_due": e.get("next_inspection_due"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


@bp.post("/substations/<sid>/environmental-inspections")
def create_environmental_inspection(sid):
    actor = get_actor()
    require_roles(actor, ["ComplianceOfficer"])
    sub = get_substation(sid)
    payload = body()
    inspection_date_raw = parse_datetime_field(payload, "inspection_date", required=True)
    inspection_date = db._format_iso(inspection_date_raw)
    largest_vessel_gal = require_number(payload, "largest_vessel_gal")
    containment_capacity_gal = require_number(payload, "containment_capacity_gal")
    rainfall_freeboard_gal = require_number(payload, "rainfall_freeboard_gal")
    method = require_enum(payload, "method", METHODS)

    ent = {
        "id": db.new_id(),
        "substation_id": sid,
        "inspection_date": inspection_date,
        "largest_vessel_gal": largest_vessel_gal,
        "containment_capacity_gal": containment_capacity_gal,
        "rainfall_freeboard_gal": rainfall_freeboard_gal,
        "method": method,
        "required_capacity_gal": None,
        "compliance": None,
        "status": "DRAFT",
        "remediation_note": None,
        "next_inspection_due": None,
    }
    db.stamp_new(ent)
    db.environmental_inspections[ent["id"]] = ent
    return success_object(inspection_view(ent), status=201)


@bp.get("/environmental-inspections")
def list_environmental_inspections():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.environmental_inspections.values())
    substation_id = request.args.get("substation_id")
    if substation_id:
        items = [e for e in items if e["substation_id"] == substation_id]
    status = request.args.get("status")
    if status:
        items = [e for e in items if e["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([inspection_view(e) for e in page], limit, offset, total)


@bp.get("/environmental-inspections/<id>")
def get_environmental_inspection_route(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    e = get_environmental_inspection(id)
    return success_object(inspection_view(e))


@bp.post("/environmental-inspections/<id>/complete")
def complete_environmental_inspection(id):
    actor = get_actor()
    require_roles(actor, ["ComplianceOfficer"])
    e = get_environmental_inspection(id)
    if e["status"] != "DRAFT":
        raise err_state_transition("Inspection is not DRAFT")

    # Compute required capacity
    required = compute_containment(e["largest_vessel_gal"], e["rainfall_freeboard_gal"], e["method"])
    e["required_capacity_gal"] = required

    # Compute compliance
    e["compliance"] = compute_compliance(e["containment_capacity_gal"], required)

    # Compute next_inspection_due
    inspection_dt = _parse_iso(e["inspection_date"])
    inspection_date = inspection_dt.date()
    months = 12 if e["compliance"] == "COMPLIANT" else 6
    next_due = _add_months(inspection_date, months)
    e["next_inspection_due"] = next_due.isoformat()

    e["status"] = "COMPLETED"
    db.touch(e)
    return success_object(inspection_view(e))


@bp.post("/environmental-inspections/<id>/close")
def close_environmental_inspection(id):
    actor = get_actor()
    require_roles(actor, ["ComplianceOfficer"])
    e = get_environmental_inspection(id)
    payload = body()
    remediation_note = payload.get("remediation_note")

    if e["status"] != "COMPLETED":
        raise err_state_transition("Inspection is not COMPLETED")

    if e.get("compliance") == "DEFICIENT" and not remediation_note:
        raise err_validation("remediation_note is required when compliance is DEFICIENT")

    if remediation_note:
        e["remediation_note"] = remediation_note

    e["status"] = "CLOSED"
    db.touch(e)
    return success_object(inspection_view(e))
