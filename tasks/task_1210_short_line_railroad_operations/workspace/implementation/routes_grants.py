"""GrantProjects and GrantMilestones (PRD 3.9)."""

from flask import Blueprint, request

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_GRANT_NOT_ACTIVE,
                    ERR_MILESTONE_VALUE_EXCEEDS_AWARD,
                    ERR_MILESTONE_NOT_SUBMITTED, not_found, invalid_state)
from util import json_body, req_str, req_int, req_num, paginate
from domain import (new_record, touch, grant_project_view, milestone_view,
                    project_milestones, compute_drawdown,
                    project_completion_check)

bp = Blueprint("grants", __name__)


# ---------------------------------------------------------------------------
# Grant projects
# ---------------------------------------------------------------------------

@bp.post("/rail/grant-projects")
def create_project():
    uid, role = authenticate()
    body = json_body(required=True)
    title = req_str(body, "title")
    grantor = req_str(body, "grantor")
    award = req_int(body, "award_amount_cents")
    if award < 0:
        raise ApiError(400, ERR_INVALID_REQUEST, "award_amount_cents must be >= 0")
    match_pct = req_num(body, "required_match_pct")
    if not (0 <= match_pct <= 100):
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "required_match_pct must be in [0, 100]")
    require_role(role, ["GrantManager"])
    rec = new_record({
        "title": title,
        "grantor": grantor,
        "award_amount_cents": award,
        "required_match_pct": match_pct,
        "status": "AWARDED",
    })
    store.grant_projects[rec["id"]] = rec
    return success_object(grant_project_view(rec), status=201)


@bp.get("/rail/grant-projects")
def list_projects():
    uid, role = authenticate()
    records = list(store.grant_projects.values())
    f_status = request.args.get("status")
    if f_status is not None:
        records = [p for p in records if p["status"] == f_status]
    limit, offset, total, page = paginate(records)
    return success_list([grant_project_view(p) for p in page], limit, offset, total)


def _get_project(pid):
    rec = store.grant_projects.get(pid)
    if rec is None:
        raise not_found("grant project not found")
    return rec


@bp.get("/rail/grant-projects/<pid>")
def get_project(pid):
    uid, role = authenticate()
    return success_object(grant_project_view(_get_project(pid)))


def _project_transition(pid, from_status, to_status, label):
    uid, role = authenticate()
    json_body()
    require_role(role, ["GrantManager"])
    project = _get_project(pid)
    if project["status"] != from_status:
        raise invalid_state("only a %s project can be %s" % (from_status, label))
    project["status"] = to_status
    touch(project)
    return success_object(grant_project_view(project))


@bp.post("/rail/grant-projects/<pid>/activate")
def activate_project(pid):
    return _project_transition(pid, "AWARDED", "ACTIVE", "activated")


@bp.post("/rail/grant-projects/<pid>/suspend")
def suspend_project(pid):
    return _project_transition(pid, "ACTIVE", "SUSPENDED", "suspended")


@bp.post("/rail/grant-projects/<pid>/resume")
def resume_project(pid):
    return _project_transition(pid, "SUSPENDED", "ACTIVE", "resumed")


@bp.post("/rail/grant-projects/<pid>/milestones")
def create_milestone(pid):
    uid, role = authenticate()
    body = json_body(required=True)
    name = req_str(body, "name")
    value = req_int(body, "milestone_value_cents")
    if value < 0:
        raise ApiError(400, ERR_INVALID_REQUEST, "milestone_value_cents must be >= 0")
    require_role(role, ["GrantManager"])
    # Nested path: the parent project resolves first (PRD 2.6).
    project = _get_project(pid)
    # Budget guard: sum over non-REJECTED milestones, including the new one,
    # must not exceed the award.
    total = sum(m["milestone_value_cents"] for m in project_milestones(pid)
                if m["status"] != "REJECTED")
    if total + value > project["award_amount_cents"]:
        raise ApiError(422, ERR_MILESTONE_VALUE_EXCEEDS_AWARD,
                       "non-rejected milestone values would exceed the award")
    rec = new_record({
        "project_id": pid,
        "name": name,
        "milestone_value_cents": value,
        "actual_cost_cents": None,
        "status": "PENDING",
        "drawdown_cents": None,
        "submitted_at": None,
    })
    store.grant_milestones[rec["id"]] = rec
    return success_object(milestone_view(rec), status=201)


# ---------------------------------------------------------------------------
# Grant milestones
# ---------------------------------------------------------------------------

@bp.get("/rail/grant-milestones")
def list_milestones():
    uid, role = authenticate()
    records = list(store.grant_milestones.values())
    f_project = request.args.get("project_id")
    f_status = request.args.get("status")
    if f_project is not None:
        records = [m for m in records if m["project_id"] == f_project]
    if f_status is not None:
        records = [m for m in records if m["status"] == f_status]
    limit, offset, total, page = paginate(records)
    return success_list([milestone_view(m) for m in page], limit, offset, total)


def _get_milestone(mid):
    rec = store.grant_milestones.get(mid)
    if rec is None:
        raise not_found("grant milestone not found")
    return rec


@bp.get("/rail/grant-milestones/<mid>")
def get_milestone(mid):
    uid, role = authenticate()
    return success_object(milestone_view(_get_milestone(mid)))


@bp.post("/rail/grant-milestones/<mid>/submit")
def submit_milestone(mid):
    uid, role = authenticate()
    body = json_body(required=True)
    actual_cost = req_int(body, "actual_cost_cents")
    if actual_cost < 0:
        raise ApiError(400, ERR_INVALID_REQUEST, "actual_cost_cents must be >= 0")
    require_role(role, ["GrantManager"])
    milestone = _get_milestone(mid)
    if milestone["status"] not in ("PENDING", "REJECTED"):
        raise invalid_state("only a PENDING or REJECTED milestone can be submitted")
    project = store.grant_projects.get(milestone["project_id"])
    if project is None or project["status"] != "ACTIVE":
        raise ApiError(409, ERR_GRANT_NOT_ACTIVE, "project is not ACTIVE")
    milestone["actual_cost_cents"] = actual_cost
    milestone["submitted_at"] = store.now
    milestone["status"] = "SUBMITTED"
    touch(milestone)
    return success_object(milestone_view(milestone))


@bp.post("/rail/grant-milestones/<mid>/approve")
def approve_milestone(mid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["RegulatorOfficer"])
    milestone = _get_milestone(mid)
    if milestone["status"] != "SUBMITTED":
        raise ApiError(409, ERR_MILESTONE_NOT_SUBMITTED,
                       "only a SUBMITTED milestone can be approved")
    project = store.grant_projects.get(milestone["project_id"])
    if project is None or project["status"] != "ACTIVE":
        raise ApiError(409, ERR_GRANT_NOT_ACTIVE, "project is not ACTIVE")
    milestone["drawdown_cents"] = compute_drawdown(project, milestone)
    milestone["status"] = "APPROVED"
    touch(milestone)
    return success_object(milestone_view(milestone))


@bp.post("/rail/grant-milestones/<mid>/reject")
def reject_milestone(mid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["RegulatorOfficer"])
    milestone = _get_milestone(mid)
    if milestone["status"] != "SUBMITTED":
        raise ApiError(409, ERR_MILESTONE_NOT_SUBMITTED,
                       "only a SUBMITTED milestone can be rejected")
    milestone["status"] = "REJECTED"
    touch(milestone)
    return success_object(milestone_view(milestone))


@bp.post("/rail/grant-milestones/<mid>/pay")
def pay_milestone(mid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["SettlementClerk"])
    milestone = _get_milestone(mid)
    if milestone["status"] != "APPROVED":
        raise invalid_state("only an APPROVED milestone can be paid")
    project = store.grant_projects.get(milestone["project_id"])
    if project is None or project["status"] != "ACTIVE":
        raise ApiError(409, ERR_GRANT_NOT_ACTIVE, "project is not ACTIVE")
    milestone["status"] = "PAID"
    touch(milestone)
    project_completion_check(project)
    return success_object(milestone_view(milestone))
