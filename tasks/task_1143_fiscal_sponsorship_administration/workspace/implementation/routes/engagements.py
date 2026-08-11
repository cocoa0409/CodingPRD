"""StaffEngagement endpoints (PRD §3.5)."""

from datetime import date

from flask import Blueprint, request

from db import agreement_of_project, new_id, parse_iso_date, stamp_new, store, touch
from envelope import ok_list, ok_obj
from errors import (
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_DUPLICATE_ENGAGEMENT,
    ERR_ENGAGEMENT_DATES_INVALID,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_ENGAGEMENT_OVERLAP,
    ERR_ENGAGEMENT_STATE_INVALID,
    ERR_MODEL_FORBIDS_EMPLOYMENT,
    ERR_PROJECT_NOT_FOUND,
    ERR_SEVERE_POSTURE_BLOCKS_SPEND,
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

bp = Blueprint("engagements", __name__)

ENGAGEMENT_TYPES = ("EMPLOYEE", "CONTRACTOR")
COMPENSATION_TYPES = ("HOURLY", "SALARY", "FIXED")
PIPELINE_STATES = ("PROPOSED", "VETTED", "CLASSIFICATION_REVIEW")


def get_engagement(engagement_id):
    eng = store.engagements.get(engagement_id)
    if eng is None:
        raise_err(ERR_ENGAGEMENT_NOT_FOUND, "staff engagement not found")
    return eng


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; null end is open-ended; touching
    endpoints (end == start) do NOT overlap."""
    a_end = a_end or date.max
    b_end = b_end or date.max
    return a_start < b_end and b_start < a_end


@bp.post("/fsa/projects/<project_id>/staff-engagements")
def create_engagement(project_id):
    data = body()
    worker_name = req_str(data, "worker_name")
    worker_email = req_str(data, "worker_email")
    engagement_type = req_enum(data, "engagement_type", ENGAGEMENT_TYPES)
    compensation_type = req_enum(data, "compensation_type", COMPENSATION_TYPES)
    rate = req_int(data, "rate_cents")
    start_date = req_str(data, "start_date")
    end_date = opt_str(data, "end_date")
    if rate < 1:
        raise_err(ERR_VALIDATION, "rate_cents must be >= 1")
    start = parse_iso_date(start_date)
    if start is None:
        raise_err(ERR_VALIDATION, "start_date must be an ISO date (YYYY-MM-DD)")
    end = None
    if end_date is not None:
        end = parse_iso_date(end_date)
        if end is None:
            raise_err(ERR_VALIDATION, "end_date must be an ISO date (YYYY-MM-DD)")
    uid, role = auth()
    require_role(role, {"ProjectLead"})
    require_owner(uid, project_id)
    project = store.projects.get(project_id)
    if project is None:
        raise_err(ERR_PROJECT_NOT_FOUND, "project not found")
    # employment classification legality (rule 8)
    agreement = agreement_of_project(project["id"])
    if engagement_type == "EMPLOYEE" and agreement and agreement["model"] == "PRE_APPROVED_GRANT":
        raise_err(ERR_MODEL_FORBIDS_EMPLOYMENT, "EMPLOYEE engagements require COMPREHENSIVE model")
    # duplicate pipeline-stage engagement for the same worker (rule 14)
    for e in store.engagements.values():
        if (
            e["project_id"] == project["id"]
            and e["worker_email"] == worker_email
            and e["status"] in PIPELINE_STATES
        ):
            raise_err(ERR_DUPLICATE_ENGAGEMENT, "worker already has a non-terminal engagement on this project")
    # interval sanity (rule 21)
    if end is not None and end <= start:
        raise_err(ERR_ENGAGEMENT_DATES_INVALID, "end_date must be later than start_date")
    eng = stamp_new({
        "id": new_id(),
        "project_id": project["id"],
        "worker_name": worker_name,
        "worker_email": worker_email,
        "engagement_type": engagement_type,
        "classification_overridden": False,
        "compensation_type": compensation_type,
        "rate_cents": rate,
        "start_date": start_date,
        "end_date": end_date,
        "status": "PROPOSED",
        "contractor_ytd_cents": 0,
        "ytd_year": None,
        "requires_1099": False,
    })
    eng["_proposed_type"] = engagement_type
    eng["_start"] = start
    eng["_end"] = end
    store.engagements[eng["id"]] = eng
    return ok_obj(eng, 201)


@bp.get("/fsa/staff-engagements/<engagement_id>")
def get_engagement_route(engagement_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    return ok_obj(get_engagement(engagement_id))


@bp.get("/fsa/projects/<project_id>/staff-engagements")
def list_engagements(project_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    if project_id not in store.projects:
        raise_err(ERR_PROJECT_NOT_FOUND, "project not found")
    items = [e for e in store.engagements.values() if e["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    worker_email = request.args.get("worker_email")
    if worker_email is not None:
        items = [e for e in items if e["worker_email"] == worker_email]
    return ok_list(items)


@bp.post("/fsa/staff-engagements/<engagement_id>/classification-review")
def classification_review(engagement_id):
    data = body()
    approved_type = req_enum(data, "approved_type", ENGAGEMENT_TYPES)
    rationale = req_str(data, "rationale")
    uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    eng = get_engagement(engagement_id)
    if eng["status"] not in ("PROPOSED", "CLASSIFICATION_REVIEW"):
        raise_err(ERR_ENGAGEMENT_STATE_INVALID, "engagement cannot be vetted from %s" % eng["status"])
    agreement = agreement_of_project(eng["project_id"])
    if approved_type == "EMPLOYEE" and agreement and agreement["model"] == "PRE_APPROVED_GRANT":
        raise_err(ERR_MODEL_FORBIDS_EMPLOYMENT, "EMPLOYEE approvals require COMPREHENSIVE model")
    eng["engagement_type"] = approved_type
    eng["classification_overridden"] = approved_type != eng["_proposed_type"]
    eng["status"] = "VETTED"
    touch(eng)
    return ok_obj(eng)


@bp.post("/fsa/staff-engagements/<engagement_id>/activate")
def activate_engagement(engagement_id):
    uid, role = auth()
    require_role(role, {"ProjectLead"})
    eng = get_engagement(engagement_id)
    require_owner(uid, eng["project_id"])
    if eng["status"] != "VETTED":
        raise_err(ERR_ENGAGEMENT_STATE_INVALID, "engagement is not VETTED")
    agreement = agreement_of_project(eng["project_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise_err(ERR_AGREEMENT_NOT_ACTIVE, "agreement is not ACTIVE")
    project = store.projects.get(eng["project_id"])
    if project and project["oversight_posture"] != "NORMAL":
        raise_err(ERR_SEVERE_POSTURE_BLOCKS_SPEND, "oversight posture blocks staff activation")
    for other in store.engagements.values():
        if (
            other["id"] != eng["id"]
            and other["project_id"] == eng["project_id"]
            and other["worker_email"] == eng["worker_email"]
            and other["status"] == "ACTIVE"
            and _intervals_overlap(eng["_start"], eng["_end"], other["_start"], other["_end"])
        ):
            raise_err(ERR_ENGAGEMENT_OVERLAP, "interval overlaps an existing ACTIVE engagement")
    eng["status"] = "ACTIVE"
    touch(eng)
    return ok_obj(eng)


@bp.post("/fsa/staff-engagements/<engagement_id>/flag-misclassification")
def flag_misclassification(engagement_id):
    data = body()
    req_str(data, "reason")
    uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    eng = get_engagement(engagement_id)
    if eng["status"] != "ACTIVE":
        raise_err(ERR_ENGAGEMENT_STATE_INVALID, "engagement is not ACTIVE")
    eng["status"] = "CLASSIFICATION_REVIEW"
    touch(eng)
    return ok_obj(eng)


@bp.post("/fsa/staff-engagements/<engagement_id>/terminate")
def terminate_engagement(engagement_id):
    data = body()
    end_date = opt_str(data, "end_date")
    opt_str(data, "reason")
    end = None
    if end_date is not None:
        end = parse_iso_date(end_date)
        if end is None:
            raise_err(ERR_VALIDATION, "end_date must be an ISO date (YYYY-MM-DD)")
    uid, role = auth()
    require_role(role, {"ProjectLead", "ComplianceOfficer"})
    eng = get_engagement(engagement_id)
    if role == "ProjectLead":
        require_owner(uid, eng["project_id"])
    if eng["status"] not in ("ACTIVE", "VETTED", "CLASSIFICATION_REVIEW"):
        raise_err(ERR_ENGAGEMENT_STATE_INVALID, "engagement cannot be terminated from %s" % eng["status"])
    if eng["status"] == "ACTIVE" and end_date is not None:
        eng["end_date"] = end_date
        eng["_end"] = end
    eng["status"] = "TERMINATED"
    touch(eng)
    return ok_obj(eng)
