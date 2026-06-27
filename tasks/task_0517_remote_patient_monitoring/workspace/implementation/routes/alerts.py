"""ThresholdAlert endpoints + triage lifecycle (PRD §3.6)."""
from flask import Blueprint, g, request

import errors
import serializers
from common import parse_pagination, sort_by_created, paginate
from db import db, stamp_create, touch
from middleware import require_roles
from response import object_response, array_response
from services import lookups

bp = Blueprint("alerts", __name__)

ALERT_STATUSES = {"OPEN", "ACKNOWLEDGED", "ESCALATED", "RESOLVED"}


def _get_alert_or_404(alert_id):
    rec = db.alerts.get(alert_id)
    if rec is None:
        raise errors.not_found("Alert not found.")
    return rec


@bp.get("/alerts")
@require_roles("Clinician", "Physician", "CareCoordinator")
def list_alerts():
    limit, offset = parse_pagination()
    records = list(db.alerts.values())
    patient_id = request.args.get("patient_id")
    if patient_id is not None:
        records = [r for r in records if r["patient_id"] == patient_id]
    vitals_reading_id = request.args.get("vitals_reading_id")
    if vitals_reading_id is not None:
        records = [r for r in records
                   if r["vitals_reading_id"] == vitals_reading_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serializers.alert(r) for r in page],
                          limit, offset, total)


@bp.get("/alerts/<alert_id>")
@require_roles("Clinician", "Physician", "CareCoordinator")
def get_alert(alert_id):
    rec = _get_alert_or_404(alert_id)
    return object_response(serializers.alert(rec))


@bp.post("/alerts/<alert_id>/acknowledge")
@require_roles("Clinician")
def acknowledge_alert(alert_id):
    rec = _get_alert_or_404(alert_id)
    if rec["status"] != "OPEN":
        raise errors.invalid_state("Only an OPEN alert can be acknowledged.")
    rec["status"] = "ACKNOWLEDGED"
    rec["acknowledged_by_user_id"] = g.user_id
    touch(rec)
    return object_response(serializers.alert(rec))


@bp.post("/alerts/<alert_id>/escalate")
@require_roles("Clinician")
def escalate_alert(alert_id):
    rec = _get_alert_or_404(alert_id)
    # State legality (priority 6): escalate defined from OPEN or ACKNOWLEDGED.
    if rec["status"] not in ("OPEN", "ACKNOWLEDGED"):
        raise errors.invalid_state("Alert cannot be escalated from its current state.")
    # Safety (priority 8): escalate requires CRITICAL severity.
    if rec["severity"] != "CRITICAL":
        raise errors.ApiError(errors.ERR_ESCALATION_NOT_PERMITTED, 409,
                              "Only a CRITICAL alert can be escalated.")
    rec["status"] = "ESCALATED"
    touch(rec)

    # Cascade: create a ReviewTask (priority=URGENT) linked to this alert.
    task = {
        "patient_id": rec["patient_id"],
        "threshold_alert_id": rec["id"],
        "escalated_from_task_id": None,
        "priority": "URGENT",  # source severity is CRITICAL
        "status": "QUEUED",
        "reviewer_user_id": None,
    }
    stamp_create(task)
    db.review_tasks[task["id"]] = task

    return object_response(serializers.alert(rec))


@bp.post("/alerts/<alert_id>/resolve")
@require_roles("Clinician")
def resolve_alert(alert_id):
    rec = _get_alert_or_404(alert_id)
    # State legality: resolve defined from ACKNOWLEDGED.
    if rec["status"] != "ACKNOWLEDGED":
        raise errors.invalid_state("Only an ACKNOWLEDGED alert can be resolved.")
    # Safety (priority 9): no linked ReviewTask in QUEUED/IN_REVIEW/ESCALATED.
    for t in lookups.review_tasks_for_alert(alert_id):
        if t["status"] in ("QUEUED", "IN_REVIEW", "ESCALATED"):
            raise errors.ApiError(errors.ERR_OPEN_REVIEW_TASK, 409,
                                  "A linked review task is still open.")
    rec["status"] = "RESOLVED"
    touch(rec)
    return object_response(serializers.alert(rec))
