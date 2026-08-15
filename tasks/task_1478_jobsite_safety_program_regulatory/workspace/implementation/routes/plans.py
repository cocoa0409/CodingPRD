from flask import Blueprint

from db import store, now
from helpers import (
    require_roles,
    body,
    reject_unknown,
    f_str,
    f_date,
    f_int,
    ok,
    paginate,
)
from errors import ApiError
from services import get_plan, get_project, new_entity, ser_plan, bump

bp = Blueprint("plans", __name__)

ALL_ROLES = (
    "SafetyManager",
    "SiteSuperintendent",
    "SafetyInspector",
    "SubcontractorRep",
    "ComplianceAuditor",
)


@bp.route("/safety/safety-plans", methods=["POST"])
def create_plan():
    require_roles("SafetyManager")
    b = body()
    # priority 3: body FK existence
    raw_pid = b.get("project_id")
    if isinstance(raw_pid, str):
        get_project(raw_pid)
    # priority 4: shape
    reject_unknown(b, {"project_id", "effective_date", "revision_notes"})
    project_id = f_str(b, "project_id")
    project = get_project(project_id)
    effective_date = f_date(b, "effective_date")
    revision_notes = f_str(b, "revision_notes", required=False, default="")
    existing = [p for p in store.plans.values() if p["project_id"] == project_id]
    p = new_entity()
    p.update(
        {
            "project_id": project_id,
            "effective_date": effective_date,
            "revision_notes": revision_notes,
            "revision_no": 1 + len(existing),
            "status": "DRAFT",
            "activated_at": None,
        }
    )
    store.plans[p["id"]] = p
    return ok(ser_plan(p), 201)


@bp.route("/safety/safety-plans", methods=["GET"])
def list_plans():
    require_roles(*ALL_ROLES)
    from flask import request

    records = list(store.plans.values())
    pid = request.args.get("project_id")
    if pid is not None:
        records = [p for p in records if p["project_id"] == pid]
    return paginate(records, ser_plan)


@bp.route("/safety/safety-plans/<planId>", methods=["GET"])
def get_one_plan(planId):
    require_roles(*ALL_ROLES)
    return ok(ser_plan(get_plan(planId)))


@bp.route("/safety/safety-plans/<planId>/activate", methods=["POST"])
def activate_plan(planId):
    require_roles("SafetyManager")
    plan = get_plan(planId)
    b = body()
    reject_unknown(b, {"expected_project_version"})
    expected = f_int(b, "expected_project_version")
    # state check
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT", 409, "activate requires the SafetyPlan to be DRAFT")
    project = get_project(plan["project_id"])
    # OCC on the parent project version
    if expected != project["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_project_version does not match current Project.version",
        )
    # supersede any other ACTIVE plan of the same project
    for other in store.plans.values():
        if (
            other["project_id"] == project["id"]
            and other["id"] != plan["id"]
            and other["status"] == "ACTIVE"
        ):
            other["status"] = "SUPERSEDED"
            bump(other)
    plan["status"] = "ACTIVE"
    plan["activated_at"] = now()
    bump(plan)
    project["current_active_plan_id"] = plan["id"]
    bump(project)  # Project.version increments by 1
    return ok(ser_plan(plan))
