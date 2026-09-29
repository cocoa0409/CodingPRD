"""ConstructionProject endpoints (PRD 3.1)."""
from flask import Blueprint

import calc
import lookup
from db import by_project, new_row, ordered, store, touch
from enums import CAT_ZONES, CONSTRUCTION_TYPES, ENGINEERING_GRADES, PROJECT_KINDS, \
    PROJECT_STATUSES, NOTICE_STATUSES, POLICY_STATUSES
from errors import ApiError
from middleware import authenticate, body, filter_enum, get_dt, get_enum, get_int, get_str, \
    pagination, paginate, present
from response import created, ok, ok_list

bp = Blueprint("projects", __name__)


def owned_project(project, user_id, role):
    """ProjectContact identity is entity-backed: X-User-ID is the project's own id."""
    if role == "ProjectContact" and project["id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "This project does not belong to the caller.")


@bp.post("/projects")
def submit_project():
    authenticate("Underwriter", "UnderwritingManager")
    payload = body()
    name = get_str(payload, "name")
    site_address = get_str(payload, "site_address")
    construction_type = get_enum(payload, "construction_type", CONSTRUCTION_TYPES)
    project_kind = get_enum(payload, "project_kind", PROJECT_KINDS)
    hard_cost_value_cents = get_int(payload, "hard_cost_value_cents", minimum=1)
    existing_structure_value_cents = get_int(
        payload, "existing_structure_value_cents", required=False, default=0, minimum=0
    )
    cat_zone = get_enum(payload, "cat_zone", CAT_ZONES)
    planned_start_date = get_dt(payload, "planned_start_date")
    projected_completion_date = get_dt(payload, "projected_completion_date")
    if project_kind == "NEW_CONSTRUCTION" and existing_structure_value_cents != 0:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "existing_structure_value_cents must be 0 on a NEW_CONSTRUCTION submission.",
        )
    if not planned_start_date < projected_completion_date:
        raise ApiError(
            "ERR_DATE_RANGE_INVALID",
            "projected_completion_date must be strictly later than planned_start_date.",
        )
    row = new_row()
    row.update({
        "name": name,
        "site_address": site_address,
        "construction_type": construction_type,
        "project_kind": project_kind,
        "hard_cost_value_cents": hard_cost_value_cents,
        "existing_structure_value_cents": existing_structure_value_cents,
        "cat_zone": cat_zone,
        "planned_start_date": planned_start_date,
        "projected_completion_date": projected_completion_date,
        "actual_substantial_completion_date": None,
        "status": "SUBMITTED",
        "engineering_grade": None,
        "loss_control_report_ref": None,
        "screened_by_user_id": None,
        "submission_risk_score": None,
        "audit_risk_score": None,
        "in_force_policy_count": 0,
    })
    store.projects[row["id"]] = row
    return created(row)


@bp.post("/projects/<project_id>/screen")
def screen_project(project_id):
    user_id, _role = authenticate("RiskEngineer")
    project = lookup.project(project_id)
    payload = body()
    engineering_grade = get_enum(payload, "engineering_grade", ENGINEERING_GRADES)
    report_ref = get_str(payload, "loss_control_report_ref", required=False)
    if project["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_PROJECT_STATE", "Screening is available only out of SUBMITTED.")
    project["engineering_grade"] = engineering_grade
    project["loss_control_report_ref"] = report_ref
    project["screened_by_user_id"] = user_id
    score = calc.submission_basis_score(project)
    project["submission_risk_score"] = score
    if score >= calc.INELIGIBLE_THRESHOLD or engineering_grade == "D":
        project["status"] = "INELIGIBLE"
    else:
        project["status"] = "ELIGIBLE"
    touch(project)
    return ok(project)


@bp.post("/projects/<project_id>/substantial-completion")
def declare_substantial_completion(project_id):
    user_id, role = authenticate("ProjectContact", "Underwriter")
    project = lookup.project(project_id)
    owned_project(project, user_id, role)
    payload = body()
    actual = get_dt(payload, "actual_substantial_completion_date")
    if project["status"] != "UNDER_CONSTRUCTION":
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE",
            "Substantial completion may only be declared on an UNDER_CONSTRUCTION project.",
        )
    if actual > store.now():
        raise ApiError(
            "ERR_DATE_RANGE_INVALID",
            "actual_substantial_completion_date may not be later than the logical clock.",
        )
    if not actual > project["planned_start_date"]:
        raise ApiError(
            "ERR_DATE_RANGE_INVALID",
            "actual_substantial_completion_date must be later than planned_start_date.",
        )
    project["actual_substantial_completion_date"] = actual
    project["status"] = "SUBSTANTIALLY_COMPLETE"
    touch(project)
    return ok(project)


@bp.get("/projects/<project_id>")
def read_project(project_id):
    user_id, role = authenticate(
        "Underwriter", "UnderwritingManager", "RiskEngineer", "ClaimAdjuster", "ProjectContact"
    )
    project = lookup.project(project_id)
    owned_project(project, user_id, role)
    return ok(project)


@bp.get("/projects")
def list_projects():
    authenticate("Underwriter", "UnderwritingManager", "RiskEngineer")
    limit, offset = pagination()
    status = filter_enum("status", PROJECT_STATUSES)
    cat_zone = filter_enum("cat_zone", CAT_ZONES)
    project_kind = filter_enum("project_kind", PROJECT_KINDS)
    rows = ordered(list(store.projects.values()))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if cat_zone is not None:
        rows = [r for r in rows if r["cat_zone"] == cat_zone]
    if project_kind is not None:
        rows = [r for r in rows if r["project_kind"] == project_kind]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/projects/<project_id>/policies")
def list_project_policies(project_id):
    authenticate("Underwriter", "UnderwritingManager", "RiskEngineer")
    lookup.project(project_id)
    limit, offset = pagination()
    status = filter_enum("status", POLICY_STATUSES)
    rows = ordered(by_project(store.policies, project_id))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/projects/<project_id>/testing-notices")
def list_project_notices(project_id):
    user_id, role = authenticate(
        "Underwriter", "UnderwritingManager", "RiskEngineer", "ProjectContact"
    )
    project = lookup.project(project_id)
    owned_project(project, user_id, role)
    limit, offset = pagination()
    status = filter_enum("status", NOTICE_STATUSES)
    rows = ordered(by_project(store.notices, project_id))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)
