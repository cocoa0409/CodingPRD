"""Project endpoints (PRD §3.6, §3.8)."""

from flask import Blueprint, request

from db import fund_of_project, store, touch
from envelope import ok, ok_list, ok_obj
from errors import (
    ERR_FUNDS_REMAIN,
    ERR_PROJECT_NOT_ACTIVE,
    ERR_PROJECT_NOT_FOUND,
    raise_err,
)
from security import READ_ROLES, auth, body, req_str, require_role
from services import (
    available_cents,
    forward_available_cents,
    has_open_critical_incident,
    open_findings_total,
    open_incident_count,
    suspend_project_cascade,
)

bp = Blueprint("projects", __name__)


def get_project(project_id):
    project = store.projects.get(project_id)
    if project is None:
        raise_err(ERR_PROJECT_NOT_FOUND, "project not found")
    return project


@bp.get("/fsa/projects")
def list_projects():
    uid, role = auth()
    require_role(role, READ_ROLES)
    items = list(store.projects.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return ok_list(items)


@bp.get("/fsa/projects/<project_id>")
def get_project_route(project_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    return ok_obj(get_project(project_id))


@bp.get("/fsa/projects/<project_id>/summary")
def project_summary(project_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    project = get_project(project_id)
    fund = fund_of_project(project["id"])
    data = {
        "available_cents": available_cents(fund),
        "forward_available_cents": forward_available_cents(fund),
        "committed_cents": fund["committed_cents"],
        "reserved_cents": fund["reserved_cents"],
        "risk_score": project["risk_score"],
        "oversight_posture": project["oversight_posture"],
        "open_findings_count": open_findings_total(project["id"]),
        "open_incident_count": open_incident_count(project["id"]),
    }
    return ok(data)


@bp.post("/fsa/projects/<project_id>/suspend")
def suspend_project(project_id):
    data = body()
    reason = req_str(data, "reason")
    uid, role = auth()
    require_role(role, {"ComplianceOfficer", "SponsorAdmin"})
    project = get_project(project_id)
    if project["status"] != "ACTIVE":
        raise_err(ERR_PROJECT_NOT_ACTIVE, "project is not ACTIVE")
    suspend_project_cascade(project, reason)
    return ok_obj(project)


@bp.post("/fsa/projects/<project_id>/reinstate")
def reinstate_project(project_id):
    uid, role = auth()
    require_role(role, {"SponsorAdmin"})
    project = get_project(project_id)
    if project["status"] != "SUSPENDED":
        raise_err(ERR_PROJECT_NOT_ACTIVE, "project is not SUSPENDED")
    # preconditions: no ESCALATED review; no open CRITICAL incident
    if any(
        r["project_id"] == project["id"] and r["status"] == "ESCALATED"
        for r in store.reviews.values()
    ):
        raise_err(ERR_PROJECT_NOT_ACTIVE, "an ESCALATED compliance review blocks reinstatement")
    if has_open_critical_incident(project["id"]):
        raise_err(ERR_PROJECT_NOT_ACTIVE, "an open CRITICAL incident blocks reinstatement")
    project["status"] = "ACTIVE"
    project["suspension_reason"] = None
    touch(project)
    fund = fund_of_project(project["id"])
    if fund and fund["status"] == "FROZEN":
        fund["status"] = "ACTIVE"
        touch(fund)
    return ok_obj(project)


@bp.post("/fsa/projects/<project_id>/terminate")
def terminate_project(project_id):
    data = body()
    reason = req_str(data, "reason")
    uid, role = auth()
    require_role(role, {"SponsorAdmin"})
    project = get_project(project_id)
    if project["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_PROJECT_NOT_ACTIVE, "project is not ACTIVE or SUSPENDED")
    fund = fund_of_project(project["id"])
    if (
        available_cents(fund) != 0
        or fund["committed_cents"] != 0
        or fund["reserved_cents"] != 0
    ):
        raise_err(ERR_FUNDS_REMAIN, "fund still holds available, committed, or reserved cents")
    project["status"] = "TERMINATED"
    touch(project)
    from db import agreement_of_project
    agreement = agreement_of_project(project["id"])
    if agreement and agreement["status"] == "ACTIVE":
        agreement["status"] = "TERMINATED"
        touch(agreement)
    fund["status"] = "CLOSED"
    touch(fund)
    return ok_obj(project)
