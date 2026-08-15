"""Incident and near-miss reports (PRD 3.4)."""

from flask import Blueprint, request

from db import store
from errors import bad_request, invalid_state, not_found
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from routes.jobs import _apply_stop_work
from util import get_body, list_paginated, new_entity, req_field, touch

bp = Blueprint("incidents", __name__)

SEVERITIES = ["NEAR_MISS", "MINOR", "SERIOUS", "MAJOR"]
INCIDENT_STATUSES = ["REPORTED", "UNDER_REVIEW", "CLOSED"]


def _get_incident(incident_id):
    incident = store.incidents.get(incident_id)
    if incident is None:
        raise not_found("Incident report not found")
    return incident


@bp.post("/v1/incidents")
def create_incident():
    require_roles(["FieldSupervisor"])
    body = get_body()
    job_id = req_field(body, "job_id")
    severity = req_field(body, "severity", choices=SEVERITIES)
    title = req_field(body, "title")
    description = req_field(body, "description")
    job = store.jobs.get(job_id)
    if job is None:
        raise not_found("Job not found")
    if job["execution_status"] not in ("MOBILIZED", "IN_PROGRESS", "FIELD_COMPLETE"):
        raise invalid_state(
            "Incidents can only be reported while the job is MOBILIZED, IN_PROGRESS or FIELD_COMPLETE")
    incident = new_entity(store.incidents, {
        "job_id": job_id,
        "severity": severity,
        "title": title,
        "description": description,
        "osha_recordable": None,
        "corrective_action": None,
        "status": "REPORTED",
    })
    # A SERIOUS or MAJOR report drives a CLEAR job to STOP_WORK and suspends
    # every ACTIVE permit — the same cascade as an explicit stop.
    if severity in ("SERIOUS", "MAJOR") and job["safety_status"] == "CLEAR":
        _apply_stop_work(job)
    return success_object(incident, status=201)


@bp.get("/v1/incidents")
def list_incidents():
    require_roles(ALL_ROLES)
    filters = {}
    for param in ("job_id", "status"):
        if request.args.get(param) is not None:
            filters[param] = request.args[param]
    page, limit, offset, total = list_paginated(store.incidents, filters,
                                                request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/incidents/<incidentId>")
def get_incident(incidentId):
    require_roles(ALL_ROLES)
    return success_object(_get_incident(incidentId))


@bp.post("/v1/incidents/<incidentId>/start-review")
def start_review(incidentId):
    require_roles(["SafetyManager"])
    incident = _get_incident(incidentId)
    if incident["status"] != "REPORTED":
        raise invalid_state("Only a REPORTED incident can move to UNDER_REVIEW")
    incident["status"] = "UNDER_REVIEW"
    touch(incident)
    return success_object(incident)


@bp.post("/v1/incidents/<incidentId>/close")
def close_incident(incidentId):
    require_roles(["SafetyManager"])
    body = get_body()
    osha_recordable = body.get("osha_recordable")
    corrective_action = body.get("corrective_action")
    if not isinstance(osha_recordable, bool):
        raise bad_request("osha_recordable is required and must be a boolean")
    if not isinstance(corrective_action, str) or corrective_action == "":
        raise bad_request("corrective_action is required")
    incident = _get_incident(incidentId)
    if incident["status"] != "UNDER_REVIEW":
        raise invalid_state("Only an UNDER_REVIEW incident can be closed")
    incident["osha_recordable"] = osha_recordable
    incident["corrective_action"] = corrective_action
    incident["status"] = "CLOSED"
    touch(incident)
    return success_object(incident)
