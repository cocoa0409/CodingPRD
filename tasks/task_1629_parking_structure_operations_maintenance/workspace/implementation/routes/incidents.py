"""Incident report endpoints (PRD 3.7)."""
from flask import Blueprint, request

import db
from errors import err_invalid_state, err_ref_not_found
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    body, require_string, require_enum, parse_pagination, paginate,
    require_ref, optional_ref, get_incident, public_view,
)

bp = Blueprint("incidents", __name__)

INCIDENT_TYPES = {"SECURITY", "VEHICLE_DAMAGE", "CASH_VARIANCE", "VANDALISM", "SAFETY"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


@bp.post("/ops/incidents")
def create_incident():
    actor = get_actor()
    require_roles(actor, ["SecurityOfficer", "ParkingAttendant", "RevenueAuditor"])
    payload = body()
    facility = require_ref(payload, db.facilities, "facility_id")
    patrol_ref = optional_ref(payload, db.patrol_rounds, "patrol_round_id")
    patrol_round_id = patrol_ref["id"] if patrol_ref else None
    recon_ref = optional_ref(payload, db.reconciliations, "reconciliation_id")
    reconciliation_id = recon_ref["id"] if recon_ref else None
    itype = require_enum(payload, "incident_type", INCIDENT_TYPES)
    severity = require_enum(payload, "severity", SEVERITIES)
    description = require_string(payload, "description")
    ent = {
        "id": db.new_id(),
        "facility_id": facility["id"],
        "patrol_round_id": patrol_round_id,
        "reconciliation_id": reconciliation_id,
        "incident_type": itype,
        "severity": severity,
        "description": description,
        "incident_status": "OPEN",
        "duplicate_of_incident_id": None,
        "auto_created": False,
        "resolution_note": None,
    }
    db.stamp_new(ent)
    db.incidents[ent["id"]] = ent
    return success_object(public_view(ent), status=201)


@bp.get("/ops/incidents/<incident_id>")
def get_incident_route(incident_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_incident(incident_id)))


@bp.get("/ops/incidents")
def list_incidents():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.incidents.values())
    for key in ("facility_id", "incident_status", "severity",
                "patrol_round_id", "reconciliation_id", "duplicate_of_incident_id"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i.get(key) == val]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(i) for i in page], limit, offset, total)


@bp.post("/ops/incidents/<incident_id>/investigate")
def investigate_incident(incident_id):
    actor = get_actor()
    require_roles(actor, ["SecurityOfficer", "RevenueAuditor"])
    inc = get_incident(incident_id)
    if inc["incident_status"] != "OPEN":
        raise err_invalid_state("only an OPEN incident may move to INVESTIGATING")
    inc["incident_status"] = "INVESTIGATING"
    db.touch(inc)
    return success_object(public_view(inc))


@bp.post("/ops/incidents/<incident_id>/resolve")
def resolve_incident(incident_id):
    actor = get_actor()
    require_roles(actor, ["SecurityOfficer", "RevenueAuditor"])
    inc = get_incident(incident_id)
    payload = body()
    note = require_string(payload, "resolution_note")
    if inc["incident_status"] != "INVESTIGATING":
        raise err_invalid_state("only an INVESTIGATING incident may be resolved")
    inc["incident_status"] = "RESOLVED"
    inc["resolution_note"] = note
    db.touch(inc)
    return success_object(public_view(inc))


@bp.post("/ops/incidents/<incident_id>/close")
def close_incident(incident_id):
    actor = get_actor()
    require_roles(actor, ["SecurityOfficer", "RevenueAuditor", "FacilityManager"])
    inc = get_incident(incident_id)
    if inc["incident_status"] not in ("OPEN", "RESOLVED"):
        raise err_invalid_state("only an OPEN or RESOLVED incident may be closed")
    inc["incident_status"] = "CLOSED"
    db.touch(inc)
    return success_object(public_view(inc))


@bp.post("/ops/incidents/<incident_id>/mark-duplicate")
def mark_duplicate(incident_id):
    actor = get_actor()
    require_roles(actor, ["SecurityOfficer"])
    inc = get_incident(incident_id)
    payload = body()
    target_id = payload.get("duplicate_of_incident_id")
    if target_id is None:
        from errors import err_validation
        raise err_validation("missing required field: duplicate_of_incident_id")
    target = db.incidents.get(target_id)
    # self-reference, unknown id, CLOSED target, or cross-facility: all ERR_REFERENCE_NOT_FOUND
    if (target is None
            or target["id"] == inc["id"]
            or target["incident_status"] == "CLOSED"
            or target["facility_id"] != inc["facility_id"]):
        raise err_ref_not_found("duplicate target must be a different, non-CLOSED incident of the same facility")
    if inc["incident_status"] not in ("OPEN", "INVESTIGATING"):
        raise err_invalid_state("only an OPEN or INVESTIGATING incident may be marked duplicate")
    inc["duplicate_of_incident_id"] = target["id"]
    inc["incident_status"] = "CLOSED"
    db.touch(inc)
    return success_object(public_view(inc))
