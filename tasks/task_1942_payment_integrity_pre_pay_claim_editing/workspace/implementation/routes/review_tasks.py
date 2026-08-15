"""ReviewTask endpoints: list/get/assign/decide/escalate."""

from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    get_body,
    pagination_params,
    require_auth,
    require_role,
    validate_body,
)
from response import success_list, success_object
from serializers import serialize
from services import core
from services.calc import MAX_IN_REVIEW_TASKS

bp = Blueprint("review_tasks", __name__)
PREFIX = "/payment-integrity"

TASK_STATUSES = {"PENDING", "IN_REVIEW", "ESCALATED", "DECIDED", "CANCELLED"}


@bp.route(PREFIX + "/review-tasks", methods=["GET"])
def list_review_tasks():
    require_auth()
    limit, offset = pagination_params()
    claim_id = request.args.get("claim_id")
    edit_hit_id = request.args.get("edit_hit_id")
    assignee = request.args.get("assigned_reviewer_user_id")
    status = request.args.get("status")
    rows = db.all_records("review_tasks")
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if edit_hit_id is not None:
        rows = [r for r in rows if r["edit_hit_id"] == edit_hit_id]
    if assignee is not None:
        rows = [r for r in rows if r.get("assigned_reviewer_user_id") == assignee]
    if status is not None:
        if status not in TASK_STATUSES:
            raise_err("ERR_INVALID_ENUM", "status filter carries undeclared member")
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return success_list([serialize(r) for r in rows[offset : offset + limit]], limit, offset, total)


def _get_task_or_404(tid):
    task = db.get("review_tasks", tid)
    if task is None:
        raise_err("ERR_REVIEW_TASK_NOT_FOUND", "Review task not found")
    return task


@bp.route(PREFIX + "/review-tasks/<tid>", methods=["GET"])
def get_review_task(tid):
    require_auth()
    return success_object(serialize(_get_task_or_404(tid)))


@bp.route(PREFIX + "/review-tasks/<tid>/assign", methods=["POST"])
def assign_task(tid):
    user_id, role = require_auth()
    require_role(role, ["SeniorReviewer"])
    body = get_body()
    vals = validate_body(
        body,
        {
            "reviewer_user_id": (True, "string", None),
            "assignee_role": (False, "string", {"Reviewer", "SeniorReviewer"}),
        },
    )
    task = _get_task_or_404(tid)
    # Guard order per PRD 3.5: state -> seniority -> capacity
    if task["status"] not in ("PENDING", "ESCALATED"):
        raise_err("ERR_REVIEW_TASK_NOT_DECIDABLE", "assign requires PENDING or ESCALATED")
    assignee_id = vals["reviewer_user_id"]
    assignee_role = vals.get("assignee_role")
    if task["status"] == "ESCALATED" and assignee_role != "SeniorReviewer":
        raise_err("ERR_SENIOR_REVIEW_REQUIRED", "ESCALATED task requires a SeniorReviewer assignee")
    in_review_count = 0
    for t in db.all_records("review_tasks"):
        if t["status"] == "IN_REVIEW" and t.get("assigned_reviewer_user_id") == assignee_id:
            in_review_count += 1
    if in_review_count >= MAX_IN_REVIEW_TASKS:
        raise_err("ERR_REVIEWER_CAPACITY_EXCEEDED", "Assignee holds MAX_IN_REVIEW_TASKS (3)")
    task["assigned_reviewer_user_id"] = assignee_id
    task["status"] = "IN_REVIEW"
    db.touch(task)
    return success_object(serialize(task))


@bp.route(PREFIX + "/review-tasks/<tid>/escalate", methods=["POST"])
def escalate_task(tid):
    user_id, role = require_auth()
    require_role(role, ["Reviewer", "SeniorReviewer"])
    body = get_body()
    validate_body(body, {"reason": (False, "string", None)})
    task = _get_task_or_404(tid)
    # Band 7 state check, then band 3-style ownership (assignee identity)
    if task["status"] != "IN_REVIEW":
        raise_err("ERR_REVIEW_TASK_NOT_DECIDABLE", "escalate requires IN_REVIEW")
    if task.get("assigned_reviewer_user_id") != user_id:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Only the assigned reviewer may escalate")
    task["status"] = "ESCALATED"
    task["requires_senior"] = True
    task["assigned_reviewer_user_id"] = None
    db.touch(task)
    return success_object(serialize(task))


@bp.route(PREFIX + "/review-tasks/<tid>/decide", methods=["POST"])
def decide_task(tid):
    user_id, role = require_auth()
    require_role(role, ["Reviewer", "SeniorReviewer"])
    body = get_body()
    vals = validate_body(
        body,
        {
            "outcome": (True, "string", {"UPHOLD", "OVERRIDE"}),
            "decision_reason": (False, "string", None),
        },
    )
    task = _get_task_or_404(tid)
    if task["status"] != "IN_REVIEW":
        raise_err("ERR_REVIEW_TASK_NOT_DECIDABLE", "decide requires IN_REVIEW")
    if task.get("assigned_reviewer_user_id") != user_id:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Only the assigned reviewer may decide")
    if task.get("requires_senior") and role != "SeniorReviewer":
        raise_err("ERR_SENIOR_REVIEW_REQUIRED", "Escalated task requires SeniorReviewer")
    task["status"] = "DECIDED"
    task["outcome"] = vals["outcome"]
    task["decision_reason"] = vals.get("decision_reason", "")
    db.touch(task)
    hit = db.get("edit_hits", task["edit_hit_id"])
    if hit is not None and hit["status"] == "FIRED" and hit.get("applied"):
        if vals["outcome"] == "UPHOLD":
            core.resolve_hit_uphold(hit, user_id)
        else:
            core.resolve_hit_override(hit, hit["attributed_savings_cents"])
    return success_object(serialize(task))
