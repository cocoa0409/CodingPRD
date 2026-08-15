"""Incident report endpoints."""
from flask import Blueprint, request

from db import store
from errors import err, err_not_found, err_invalid_request
from middleware import get_auth, require_roles, err_ownership
from response import success_object, success_list, paginate
from services import cascades
from services.records import new_record, touch, public
from constants import SEVERITIES, INCIDENT_CATEGORIES, RESOLUTION_CODES
from validate import get_body, validate_body

bp = Blueprint("incidents", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]


def _get_incident(incident_id):
    i = store.incidents.get(incident_id)
    if i is None:
        raise err_not_found("incident")
    return i


@bp.post("/v1/incident-reports")
def create_incident():
    auth = get_auth()
    require_roles(auth, ["Handler", "FacilityCoordinator"])
    body = validate_body(get_body(), {
        "visit_id": ("string", True, None),
        "severity": ("string", True, SEVERITIES),
        "category": ("string", True, INCIDENT_CATEGORIES),
        "description": ("string", True, None),
    })
    if len(body["description"]) < 10:
        raise err_invalid_request("description must run at least ten characters")
    visit = store.visits.get(body["visit_id"])
    if visit is None:
        raise err_not_found("visit")
    # Ownership: the filer must be the visit's team owner or facility coordinator.
    team = store.teams.get(visit["team_id"])
    if auth.role == "Handler":
        if team is None or team["handler_id"] != auth.user_id:
            raise err_ownership()
    elif auth.role == "FacilityCoordinator":
        if visit["facility_id"] != auth.user_id:
            raise err_ownership()
    if visit["lifecycle_status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise err("ERR_VISIT_NOT_COMPLETED", 409,
                  "Incident may only be filed against an IN_PROGRESS or COMPLETED visit")
    rec = new_record(store.incidents, {
        "visit_id": visit["id"],
        "severity": body["severity"],
        "category": body["category"],
        "description": body["description"],
        "status": "FILED",
        "filed_by_role": auth.role,
        "triaged_by": None,
        "resolved_by": None,
        "resolution_code": None,
    })
    return success_object(public(rec), 201)


@bp.get("/v1/incident-reports/<incident_id>")
def get_incident(incident_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_incident(incident_id)), 200)


@bp.get("/v1/incident-reports")
def list_incidents():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.incidents.values())
    visit_id = request.args.get("visit_id")
    status = request.args.get("status")
    severity = request.args.get("severity")
    if visit_id is not None:
        records = [r for r in records if r["visit_id"] == visit_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if severity is not None:
        records = [r for r in records if r["severity"] == severity]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/v1/incident-reports/<incident_id>/triage")
def triage_incident(incident_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    inc = _get_incident(incident_id)
    if inc["status"] != "FILED":
        raise err("ERR_INCIDENT_NOT_FILED", 409, "Incident is not FILED")
    inc["status"] = "UNDER_REVIEW"
    inc["triaged_by"] = auth.user_id
    touch(inc)
    return success_object(public(inc), 200)


@bp.post("/v1/incident-reports/<incident_id>/escalate")
def escalate_incident(incident_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    inc = _get_incident(incident_id)
    if inc["status"] != "UNDER_REVIEW":
        raise err("ERR_INCIDENT_NOT_UNDER_REVIEW", 409, "Incident is not UNDER_REVIEW")
    inc["status"] = "ESCALATED"
    touch(inc)
    visit = store.visits.get(inc["visit_id"])
    if visit is not None:
        cascades.incident_escalation_cascade(visit)
    return success_object(public(inc), 200)


@bp.post("/v1/incident-reports/<incident_id>/resolve")
def resolve_incident(incident_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    inc = _get_incident(incident_id)
    body = validate_body(get_body(), {
        "resolution_code": ("string", True, RESOLUTION_CODES),
        "suspension_days": ("integer", False, None),
    })
    if body["resolution_code"] == "SUSPENSION":
        days = body.get("suspension_days")
        if days is None or not (1 <= days <= 365):
            raise err_invalid_request(
                "suspension_days (1..365) is required when resolution_code is SUSPENSION")
    if inc["status"] not in ("UNDER_REVIEW", "ESCALATED"):
        raise err("ERR_INCIDENT_NOT_RESOLVABLE", 409,
                  "Incident is not UNDER_REVIEW or ESCALATED")
    # Segregation of duties: resolver must differ from triager (final check).
    if inc.get("triaged_by") is not None and auth.user_id == inc["triaged_by"]:
        raise err("ERR_SOD_VIOLATION", 403,
                  "The resolving officer must differ from the triaging officer")
    inc["status"] = "RESOLVED"
    inc["resolved_by"] = auth.user_id
    inc["resolution_code"] = body["resolution_code"]
    touch(inc)
    cascades.incident_resolution_effects(inc, body["resolution_code"],
                                         body.get("suspension_days"))
    return success_object(public(inc), 200)
