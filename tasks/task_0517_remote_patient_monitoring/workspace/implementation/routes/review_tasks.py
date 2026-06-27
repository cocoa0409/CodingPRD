"""ReviewTask endpoints: provider review queue (PRD §3.6)."""
from flask import Blueprint, g, request

import errors
import serializers
from common import parse_pagination, paginate
from db import db, stamp_create, touch
from middleware import require_roles
from response import object_response, array_response
from services import lookups

bp = Blueprint("review_tasks", __name__)


def _get_task_or_404(task_id):
    rec = db.review_tasks.get(task_id)
    if rec is None:
        raise errors.not_found("Review task not found.")
    return rec


def _queue_sort_key(task):
    # URGENT before ROUTINE; then created_at ASC; final tie-break the task's
    # own creation sequence (deterministic, never a random id) — PRD §3.6.
    priority_rank = 0 if task["priority"] == "URGENT" else 1
    return (priority_rank, task["created_at"], task["_seq"])


@bp.get("/review-tasks")
@require_roles("Physician")
def list_review_tasks():
    limit, offset = parse_pagination()
    records = list(db.review_tasks.values())
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    priority = request.args.get("priority")
    if priority is not None:
        records = [r for r in records if r["priority"] == priority]
    patient_id = request.args.get("patient_id")
    if patient_id is not None:
        records = [r for r in records if r["patient_id"] == patient_id]
    threshold_alert_id = request.args.get("threshold_alert_id")
    if threshold_alert_id is not None:
        records = [r for r in records
                   if r["threshold_alert_id"] == threshold_alert_id]
    escalated_from_task_id = request.args.get("escalated_from_task_id")
    if escalated_from_task_id is not None:
        records = [r for r in records
                   if r["escalated_from_task_id"] == escalated_from_task_id]

    # Queue ordering: URGENT-first then created_at ASC (PRD §3.6).
    records = sorted(records, key=_queue_sort_key)
    page, total = paginate(records, limit, offset)
    return array_response([serializers.review_task(r) for r in page],
                          limit, offset, total)


@bp.get("/review-tasks/<task_id>")
@require_roles("Physician")
def get_review_task(task_id):
    rec = _get_task_or_404(task_id)
    return object_response(serializers.review_task(rec))


@bp.post("/review-tasks/<task_id>/claim")
@require_roles("Physician")
def claim_review_task(task_id):
    rec = _get_task_or_404(task_id)
    if rec["status"] != "QUEUED":
        raise errors.invalid_state("Only a QUEUED task can be claimed.")
    rec["status"] = "IN_REVIEW"
    rec["reviewer_user_id"] = g.user_id
    touch(rec)

    # Cascade: linked ThresholdAlert ESCALATED -> ACKNOWLEDGED (de-escalation).
    alert = db.alerts.get(rec["threshold_alert_id"])
    if alert is not None and alert["status"] == "ESCALATED":
        alert["status"] = "ACKNOWLEDGED"
        touch(alert)

    return object_response(serializers.review_task(rec))


@bp.post("/review-tasks/<task_id>/sign")
@require_roles("Physician")
def sign_review_task(task_id):
    rec = _get_task_or_404(task_id)
    # State legality (priority 6).
    if rec["status"] != "IN_REVIEW":
        raise errors.invalid_state("Only an IN_REVIEW task can be signed.")
    signer = g.user_id
    # PRD §2.11 orders the two segregation rules: FIRST the signer must be the
    # claiming physician (ERR_NOT_TASK_OWNER), SECOND the signer must not have
    # logged any of the patient's care minutes (ERR_SEGREGATION_OF_DUTIES).
    # PRD prose order governs over the validations-table priority numbers.
    if rec["reviewer_user_id"] != signer:
        raise errors.ApiError(errors.ERR_NOT_TASK_OWNER, 403,
                              "Only the claiming physician may sign this task.")
    for a in lookups.care_activities_of_patient(rec["patient_id"]):
        if a["clinician_user_id"] == signer:
            raise errors.ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                                  "Signer logged care minutes for this patient.")
    rec["status"] = "SIGNED"
    touch(rec)
    return object_response(serializers.review_task(rec))


@bp.post("/review-tasks/<task_id>/escalate")
@require_roles("Physician")
def escalate_review_task(task_id):
    rec = _get_task_or_404(task_id)
    if rec["status"] != "IN_REVIEW":
        raise errors.invalid_state("Only an IN_REVIEW task can be escalated.")
    rec["status"] = "ESCALATED"
    touch(rec)

    # Cascade: spawn a new self-referenced QUEUED task.
    child = {
        "patient_id": rec["patient_id"],
        "threshold_alert_id": rec["threshold_alert_id"],
        "escalated_from_task_id": rec["id"],
        "priority": "URGENT",
        "status": "QUEUED",
        "reviewer_user_id": None,
    }
    stamp_create(child)
    db.review_tasks[child["id"]] = child

    return object_response(serializers.review_task(rec))
