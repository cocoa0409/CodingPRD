"""OnboardingTask action endpoints (PRD §3.3)."""

from flask import Blueprint

from auth import require_roles
from db import store
from errors import (ApiError, ERR_TASK_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
                    ERR_INVALID_TASK_STATE, ERR_TASK_REQUIRED)
from helpers import touch, get_or_404, ser_task
from util import success, get_body, req_present, as_enum, as_opt_str, bad

bp = Blueprint("tasks", __name__)

DECISIONS = ("APPROVE", "REJECT")


@bp.post("/api/onboarding-tasks/<tid>/submit")
def submit_task(tid):
    uid, _ = require_roles("NewHire")
    body = get_body()
    document_ref = as_opt_str(body.get("document_ref"), "document_ref")
    note = as_opt_str(body.get("note"), "note")
    task = get_or_404("tasks", tid, ERR_TASK_NOT_FOUND, "OnboardingTask")
    # Conditional shape rule (priority 3): DOCUMENT_UPLOAD needs document_ref
    if task["task_kind"] == "DOCUMENT_UPLOAD" and not document_ref:
        bad("document_ref is required for DOCUMENT_UPLOAD tasks")
    case = store["cases"][task["case_id"]]
    # Stage 5: ownership
    if case["new_hire_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "NewHire may only submit tasks of its own case")
    # Stage 6: task state gate (rework loop allows REJECTED)
    if task["status"] not in ("PENDING", "REJECTED"):
        raise ApiError(ERR_INVALID_TASK_STATE, 409,
                       "Task is not in PENDING or REJECTED")
    task["status"] = "SUBMITTED"
    if document_ref is not None:
        task["document_ref"] = document_ref
    if note is not None:
        task["note"] = note
    touch(task)
    touch(case)
    return success(ser_task(task))


@bp.post("/api/onboarding-tasks/<tid>/review")
def review_task(tid):
    require_roles("HRAdmin")
    body = get_body()
    decision = as_enum(req_present(body, "decision"), "decision", DECISIONS)
    review_note = as_opt_str(body.get("review_note"), "review_note")
    task = get_or_404("tasks", tid, ERR_TASK_NOT_FOUND, "OnboardingTask")
    if task["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_TASK_STATE, 409,
                       "review requires a SUBMITTED task")
    case = store["cases"][task["case_id"]]
    if decision == "APPROVE":
        task["status"] = "APPROVED"
    else:
        task["status"] = "REJECTED"
        task["reject_count"] = task["reject_count"] + 1
    if review_note is not None:
        task["review_note"] = review_note
    touch(task)
    touch(case)
    return success(ser_task(task))


@bp.post("/api/onboarding-tasks/<tid>/waive")
def waive_task(tid):
    require_roles("HRAdmin")
    get_body()
    task = get_or_404("tasks", tid, ERR_TASK_NOT_FOUND, "OnboardingTask")
    # Stage 6: state gate
    if task["status"] not in ("PENDING", "REJECTED"):
        raise ApiError(ERR_INVALID_TASK_STATE, 409,
                       "waive requires a PENDING or REJECTED task")
    # Stage 9: required tasks can never be waived
    if task["is_required"]:
        raise ApiError(ERR_TASK_REQUIRED, 422,
                       "Required tasks cannot be waived")
    case = store["cases"][task["case_id"]]
    task["status"] = "WAIVED"
    touch(task)
    touch(case)
    return success(ser_task(task))
