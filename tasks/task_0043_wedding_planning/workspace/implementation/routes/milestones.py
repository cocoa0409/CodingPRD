"""Milestone routes."""
from flask import Blueprint, request

import db
from errors import (
    raise_error,
    ERR_VERSION_CONFLICT,
    ERR_MILESTONE_NOT_PENDING,
    ERR_MILESTONE_NOT_IN_PROGRESS,
    ERR_MILESTONE_PERCENTAGES_INVALID,
    ERR_PROJECT_NOT_IN_DRAFT,
)
from middleware import require_roles, check_planner_owns_project
from response import success, list_response, parse_pagination
from services.lookup import (
    get_project,
    get_milestone,
    assert_project_not_terminal,
)


bp = Blueprint("milestones", __name__)


def _validate_percent_sum(project_id: str):
    total = round(sum(
        float(m["percent_of_budget"])
        for m in db.milestones.values()
        if m["project_id"] == project_id
    ), 6)
    if total != 100.0:
        # Spec: re-validated after every milestone create/update/delete on a project in DRAFT/PLANNING
        # but the rule says "MUST sum to exactly 100.0" — we only enforce on activation actually,
        # but we choose to enforce a non-100 result as INVALID per the validation table.
        # However: PRD says "While a project remains in DRAFT, milestones may be created, updated,
        # or deleted freely. After every such mutation — and again as a precondition to leaving DRAFT
        # — the sum of percent_of_budget across all milestones on the project MUST equal exactly 100.0;
        # if it does not, the mutation or activation is rejected". So enforce on every mutation.
        raise_error(ERR_MILESTONE_PERCENTAGES_INVALID,
                    f"Milestone percentages sum to {total}, must be 100.0")


@bp.post("/wedding-projects/<project_id>/milestones")
def create_milestone(project_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    body = request.get_json(silent=True) or {}
    milestone = {
        "project_id": project_id,
        "label": body.get("label"),
        "due_at": int(body.get("due_at")) if body.get("due_at") is not None else None,
        "percent_of_budget": float(body.get("percent_of_budget", 0)),
        "status": "PENDING",
    }
    db.add_common_create(milestone)
    db.milestones[milestone["id"]] = milestone
    try:
        _validate_percent_sum(project_id)
    except Exception:
        # Roll back the create
        del db.milestones[milestone["id"]]
        raise
    return success(milestone, status=201)


@bp.get("/wedding-projects/<project_id>/milestones")
def list_milestones(project_id):
    require_roles("Planner", "Auditor", "Couple")
    p = get_project(project_id)
    if request.headers.get("X-User-Role") == "Planner":
        check_planner_owns_project(p)
    limit, offset = parse_pagination(request.args)
    items = [m for m in db.milestones.values() if m["project_id"] == project_id]
    items.sort(key=lambda m: m["created_at"])
    return list_response(items, limit, offset)


@bp.patch("/wedding-projects/<project_id>/milestones/<milestone_id>")
def update_milestone(project_id, milestone_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    m = get_milestone(project_id, milestone_id)
    body = request.get_json(silent=True) or {}

    # Status transition pre-OCC because state-precondition has higher priority? Actually OCC is last (priority 15).
    # Apply state-transition checks first.
    new_status = body.get("status")
    new_label = body.get("label")
    new_due = body.get("due_at")
    new_pct = body.get("percent_of_budget")
    new_version = body.get("version")

    if new_status is not None:
        if new_status == "IN_PROGRESS":
            if m["status"] != "PENDING":
                raise_error(ERR_MILESTONE_NOT_PENDING, "Milestone must be PENDING")
        elif new_status == "COMPLETED":
            if m["status"] != "IN_PROGRESS":
                raise_error(ERR_MILESTONE_NOT_IN_PROGRESS, "Milestone must be IN_PROGRESS")
        else:
            raise_error(ERR_MILESTONE_NOT_PENDING, f"Invalid status target: {new_status}")

    # OCC last
    if new_version is not None and int(new_version) != int(m["version"]):
        raise_error(ERR_VERSION_CONFLICT, "Version mismatch")

    # Apply changes
    if new_label is not None:
        m["label"] = new_label
    if new_due is not None:
        m["due_at"] = int(new_due)
    if new_pct is not None:
        m["percent_of_budget"] = float(new_pct)
    if new_status is not None:
        m["status"] = new_status
    db.bump(m)

    # Re-validate percent sum if relevant; only when project still DRAFT or PLANNING
    if new_pct is not None and p["status"] in ("DRAFT", "PLANNING"):
        _validate_percent_sum(project_id)

    return success(m)


@bp.delete("/wedding-projects/<project_id>/milestones/<milestone_id>")
def delete_milestone(project_id, milestone_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    m = get_milestone(project_id, milestone_id)
    if p["status"] != "DRAFT":
        raise_error(ERR_PROJECT_NOT_IN_DRAFT,
                    "Milestones may only be deleted while project is DRAFT")
    del db.milestones[milestone_id]
    # Re-validate percent sum: an empty set is allowed (no milestones on a draft is fine);
    # a non-empty set must sum to 100.0
    remaining = [mm for mm in db.milestones.values() if mm["project_id"] == project_id]
    if remaining:
        try:
            _validate_percent_sum(project_id)
        except Exception:
            # Restore
            db.milestones[milestone_id] = m
            raise
    return success({}, status=204)
