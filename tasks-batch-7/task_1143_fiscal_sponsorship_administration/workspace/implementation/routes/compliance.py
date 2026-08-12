"""ComplianceReview and RiskIncident endpoints (PRD §3.6)."""

from flask import Blueprint, request

from db import new_id, stamp_new, store, touch
from envelope import ok_list, ok_obj
from errors import (
    ERR_INCIDENT_NOT_FOUND,
    ERR_INCIDENT_STATE_INVALID,
    ERR_PROJECT_NOT_FOUND,
    ERR_REMEDIATION_EXCEEDS_OPEN,
    ERR_REVIEW_NOT_FOUND,
    ERR_REVIEW_STATE_INVALID,
    ERR_VALIDATION,
    raise_err,
)
from security import (
    READ_ROLES,
    auth,
    body,
    opt_str,
    req_enum,
    req_int,
    req_str,
    require_owner,
    require_role,
)
from services import recompute_risk, suspend_project_cascade

bp = Blueprint("compliance", __name__)

REVIEW_TYPES = ("SCHEDULED", "TRIGGERED")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
CATEGORIES = ("LIABILITY", "FINANCIAL", "REPUTATIONAL", "REGULATORY", "SAFETY")
INCIDENT_ACTIONS = ("TRIAGE", "MITIGATE", "RESOLVE", "DISMISS")
INCIDENT_TRANSITIONS = {
    "TRIAGE": (("REPORTED",), "TRIAGED"),
    "MITIGATE": (("TRIAGED",), "MITIGATING"),
    "RESOLVE": (("REPORTED", "TRIAGED", "MITIGATING"), "RESOLVED"),
    "DISMISS": (("REPORTED", "TRIAGED"), "DISMISSED"),
}


# ---------------------------------------------------------------------------
# Compliance reviews
# ---------------------------------------------------------------------------


def get_review(review_id):
    review = store.reviews.get(review_id)
    if review is None:
        raise_err(ERR_REVIEW_NOT_FOUND, "compliance review not found")
    return review


@bp.post("/fsa/projects/<project_id>/compliance-reviews")
def create_review(project_id):
    data = body()
    review_type = req_enum(data, "review_type", REVIEW_TYPES)
    note = opt_str(data, "note")
    uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    if project_id not in store.projects:
        raise_err(ERR_PROJECT_NOT_FOUND, "project not found")
    review = stamp_new({
        "id": new_id(),
        "project_id": project_id,
        "review_type": review_type,
        "status": "OPEN",
        "findings_count": 0,
        "open_findings_count": 0,
        "severity_max": None,
        "note": note,
    })
    store.reviews[review["id"]] = review
    return ok_obj(review, 201)


@bp.get("/fsa/compliance-reviews/<review_id>")
def get_review_route(review_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    return ok_obj(get_review(review_id))


@bp.get("/fsa/projects/<project_id>/compliance-reviews")
def list_reviews(project_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    if project_id not in store.projects:
        raise_err(ERR_PROJECT_NOT_FOUND, "project not found")
    items = [r for r in store.reviews.values() if r["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return ok_list(items)


@bp.post("/fsa/compliance-reviews/<review_id>/issue-findings")
def issue_findings(review_id):
    data = body()
    findings_count = req_int(data, "findings_count")
    severity_max = req_enum(data, "severity_max", SEVERITIES)
    if findings_count < 1:
        raise_err(ERR_VALIDATION, "findings_count must be >= 1")
    uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    review = get_review(review_id)
    if review["status"] != "OPEN":
        raise_err(ERR_REVIEW_STATE_INVALID, "review is not OPEN")
    review["findings_count"] = findings_count
    review["open_findings_count"] = findings_count
    review["severity_max"] = severity_max
    review["status"] = "FINDINGS_ISSUED"
    touch(review)
    project = store.projects.get(review["project_id"])
    if project:
        recompute_risk(project)
    return ok_obj(review)


@bp.post("/fsa/compliance-reviews/<review_id>/remediate")
def remediate(review_id):
    data = body()
    remediated_count = req_int(data, "remediated_count")
    uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    review = get_review(review_id)
    if review["status"] != "FINDINGS_ISSUED":
        raise_err(ERR_REVIEW_STATE_INVALID, "review is not FINDINGS_ISSUED")
    if remediated_count < 1 or remediated_count > review["open_findings_count"]:
        raise_err(ERR_REMEDIATION_EXCEEDS_OPEN, "remediated_count out of bounds")
    review["open_findings_count"] -= remediated_count
    if review["open_findings_count"] == 0:
        review["status"] = "REMEDIATED"
    touch(review)
    project = store.projects.get(review["project_id"])
    if project:
        recompute_risk(project)
    return ok_obj(review)


@bp.post("/fsa/compliance-reviews/<review_id>/close")
def close_review(review_id):
    uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    review = get_review(review_id)
    if review["status"] == "OPEN" and review["findings_count"] == 0:
        pass
    elif review["status"] == "REMEDIATED":
        pass
    else:
        raise_err(ERR_REVIEW_STATE_INVALID, "review cannot be closed from %s" % review["status"])
    review["status"] = "CLOSED"
    touch(review)
    return ok_obj(review)


@bp.post("/fsa/compliance-reviews/<review_id>/escalate")
def escalate_review(review_id):
    data = body()
    req_str(data, "reason")
    uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    review = get_review(review_id)
    if review["status"] != "FINDINGS_ISSUED":
        raise_err(ERR_REVIEW_STATE_INVALID, "review is not FINDINGS_ISSUED")
    review["status"] = "ESCALATED"
    touch(review)
    project = store.projects.get(review["project_id"])
    if project:
        suspend_project_cascade(project, "ESCALATED_REVIEW")
        recompute_risk(project)
    return ok_obj(review)


# ---------------------------------------------------------------------------
# Risk incidents
# ---------------------------------------------------------------------------


def get_incident(incident_id):
    incident = store.incidents.get(incident_id)
    if incident is None:
        raise_err(ERR_INCIDENT_NOT_FOUND, "risk incident not found")
    return incident


@bp.post("/fsa/projects/<project_id>/risk-incidents")
def create_incident(project_id):
    data = body()
    category = req_enum(data, "category", CATEGORIES)
    severity = req_enum(data, "severity", SEVERITIES)
    description = req_str(data, "description")
    uid, role = auth()
    require_role(role, {"ComplianceOfficer", "ProjectLead"})
    if role == "ProjectLead":
        require_owner(uid, project_id)
    project = store.projects.get(project_id)
    if project is None:
        raise_err(ERR_PROJECT_NOT_FOUND, "project not found")
    incident = stamp_new({
        "id": new_id(),
        "project_id": project_id,
        "category": category,
        "severity": severity,
        "description": description,
        "status": "REPORTED",
        "resolution_note": None,
    })
    store.incidents[incident["id"]] = incident
    recompute_risk(project)
    return ok_obj(incident, 201)


@bp.get("/fsa/risk-incidents/<incident_id>")
def get_incident_route(incident_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    return ok_obj(get_incident(incident_id))


@bp.get("/fsa/projects/<project_id>/risk-incidents")
def list_incidents(project_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    if project_id not in store.projects:
        raise_err(ERR_PROJECT_NOT_FOUND, "project not found")
    items = [i for i in store.incidents.values() if i["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    severity = request.args.get("severity")
    if severity is not None:
        items = [i for i in items if i["severity"] == severity]
    return ok_list(items)


@bp.post("/fsa/risk-incidents/<incident_id>/transition")
def transition_incident(incident_id):
    data = body()
    action = req_enum(data, "action", INCIDENT_ACTIONS)
    note = opt_str(data, "note")
    uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    incident = get_incident(incident_id)
    from_states, to_state = INCIDENT_TRANSITIONS[action]
    if incident["status"] not in from_states:
        raise_err(ERR_INCIDENT_STATE_INVALID,
                  "incident cannot perform %s from %s" % (action, incident["status"]))
    incident["status"] = to_state
    if action in ("RESOLVE", "DISMISS") and note is not None:
        incident["resolution_note"] = note
    touch(incident)
    project = store.projects.get(incident["project_id"])
    if project:
        recompute_risk(project)
    return ok_obj(incident)
