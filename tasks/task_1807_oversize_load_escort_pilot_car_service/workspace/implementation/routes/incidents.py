"""Incident report/assess/dispute/settle with reliability cascade."""

from flask import Blueprint, request, g

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_JOB_NOT_FOUND,
    ERR_JOB_INVALID_STATE,
    ERR_INCIDENT_NOT_FOUND,
    ERR_INCIDENT_INVALID_STATE,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    raise_err,
)
from middleware import require_roles, ALL_ROLES
from mutate import mark
from response import success_object, paginate
from serializers import ser_incident
from services import calc, cascade
from util import body_json, req_enum, req_string, req_int, new_id

bp = Blueprint("incidents", __name__)


def _get_incident_or_404(incident_id):
    inc = db.incidents.get(incident_id)
    if inc is None:
        raise_err(ERR_INCIDENT_NOT_FOUND, f"Incident {incident_id} not found")
    return inc


@bp.post("/jobs/<id>/incidents")
def report_incident(id):
    uid, role = require_roles("CarrierRep", "Dispatcher", "EscortOperator")
    data = body_json(request)
    incident_type = req_enum(data, "incident_type", calc.INCIDENT_TYPES)
    description = req_string(data, "description")
    claimed = req_int(data, "claimed_amount_cents", min_v=0)
    assignment_id = data.get("assignment_id")
    if assignment_id is not None and not isinstance(assignment_id, str):
        raise_err(ERR_INVALID_REQUEST, "assignment_id must be a string")

    job = db.jobs.get(id)
    if job is None:
        raise_err(ERR_JOB_NOT_FOUND, f"Job {id} not found")

    assignment = None
    if assignment_id is not None:
        assignment = db.assignments.get(assignment_id)
        if assignment is None:
            raise_err(ERR_ASSIGNMENT_NOT_FOUND, f"Assignment {assignment_id} not found")
        leg = cascade.leg_of_assignment(assignment)
        if leg is None or leg["job_id"] != job["id"]:
            raise_err(ERR_INVALID_REQUEST,
                      "assignment_id must reference an assignment on a leg of this job")

    if job["job_status"] not in ("EN_ROUTE", "ON_HOLD", "DELIVERED"):
        raise_err(ERR_JOB_INVALID_STATE,
                  "Incidents may only be reported on an EN_ROUTE, ON_HOLD, or DELIVERED job")

    n = db.now()
    incident = {
        "id": new_id(),
        "created_at": n,
        "updated_at": n,
        "version": 1,
        "_seq": db.next_seq(),
        "job_id": job["id"],
        "assignment_id": assignment_id,
        "incident_type": incident_type,
        "description": description,
        "claimed_amount_cents": claimed,
        "reporter_role": role,
        "reporter_user_id": uid,
        "incident_status": "REPORTED",
        "escort_fault_share_pct": None,
        "assessed_amount_cents": None,
        "escort_share_cents": None,
        "assessed_by_user_id": None,
        "settled_at": None,
    }
    db.incidents[incident["id"]] = incident
    return success_object(ser_incident(incident), status=201)


@bp.get("/jobs/<id>/incidents")
def list_job_incidents(id):
    require_roles(*ALL_ROLES)
    if id not in db.jobs:
        raise_err(ERR_JOB_NOT_FOUND, f"Job {id} not found")
    rows = cascade.incidents_of_job(id)
    rows.sort(key=lambda i: (i["created_at"], i["_seq"]))
    return paginate(request, [ser_incident(i) for i in rows])


@bp.get("/incidents/<id>")
def get_incident(id):
    require_roles(*ALL_ROLES)
    return success_object(ser_incident(_get_incident_or_404(id)))


@bp.get("/incidents")
def list_incidents():
    require_roles(*ALL_ROLES)
    assignment_id = request.args.get("assignment_id")
    status = request.args.get("incident_status")
    rows = list(db.incidents.values())
    if assignment_id is not None:
        rows = [i for i in rows if i["assignment_id"] == assignment_id]
    if status is not None:
        rows = [i for i in rows if i["incident_status"] == status]
    rows.sort(key=lambda i: (i["created_at"], i["_seq"]))
    return paginate(request, [ser_incident(i) for i in rows])


@bp.post("/incidents/<id>/assess")
def assess_incident(id):
    uid, _role = require_roles("SafetyManager", "Dispatcher")
    data = body_json(request)
    pct = req_int(data, "escort_fault_share_pct", min_v=0, max_v=100)
    incident = _get_incident_or_404(id)
    if incident["incident_status"] not in ("REPORTED", "DISPUTED"):
        raise_err(ERR_INCIDENT_INVALID_STATE,
                  "Assessment requires the incident to be REPORTED or DISPUTED")
    if incident["reporter_user_id"] == uid:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "The incident reporter cannot assess it")
    assessed, escort_share = calc.assess_liability(incident["claimed_amount_cents"], pct)
    incident["escort_fault_share_pct"] = pct
    incident["assessed_amount_cents"] = assessed
    incident["escort_share_cents"] = escort_share
    incident["assessed_by_user_id"] = uid
    incident["incident_status"] = "ASSESSED"
    mark(incident)
    return success_object(ser_incident(incident))


@bp.post("/incidents/<id>/dispute")
def dispute_incident(id):
    uid, _role = require_roles("CarrierRep")
    body_json(request)
    incident = _get_incident_or_404(id)
    job = db.jobs.get(incident["job_id"])
    if job is None or job["carrier_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "CarrierRep may only dispute incidents on its own carrier's jobs")
    if incident["incident_status"] != "ASSESSED":
        raise_err(ERR_INCIDENT_INVALID_STATE, "Disputing requires the incident to be ASSESSED")
    incident["incident_status"] = "DISPUTED"
    mark(incident)
    return success_object(ser_incident(incident))


@bp.post("/incidents/<id>/settle")
def settle_incident(id):
    require_roles("FinanceManager")
    body_json(request)
    incident = _get_incident_or_404(id)
    if incident["incident_status"] != "ASSESSED":
        raise_err(ERR_INCIDENT_INVALID_STATE, "Settlement requires the incident to be ASSESSED")
    incident["settled_at"] = db.now()
    incident["incident_status"] = "SETTLED"
    mark(incident)
    if incident["assignment_id"] is not None:
        assignment = db.assignments.get(incident["assignment_id"])
        escort = db.escorts.get(assignment["escort_id"]) if assignment else None
        if escort is not None:
            new_score = calc.apply_reliability(
                escort["reliability_score"], incident["escort_fault_share_pct"])
            # Score maintenance does not by itself bump the escort version.
            escort["reliability_score"] = new_score
            if new_score < calc.RELIABILITY_SUSPENSION_FLOOR and escort["escort_status"] == "ACTIVE":
                cascade.suspend_escort_cascade(escort)
    return success_object(ser_incident(incident))
