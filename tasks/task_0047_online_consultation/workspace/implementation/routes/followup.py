"""FollowUpTask endpoints."""

from __future__ import annotations

from flask import Blueprint, request, g

import db
from middleware import require_role
from response import success
from errors import (
    AppError,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_REF_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_REMINDER_CHANNELS_INVALID,
)
from config import (
    ROLE_PATIENT, ROLE_DOCTOR, ROLE_ADMIN,
    VALID_REMINDER_CHANNELS, ABNORMAL_THRESHOLD,
)
from services.serializers import serialize
from services.occ import check_version
from services.audit import append_audit


bp = Blueprint("followup", __name__, url_prefix="/consultation/follow-up-tasks")


def _task_or_404(tid):
    row = db.find_by_id("follow_up_tasks", tid)
    if not row:
        raise AppError(ERR_NOT_FOUND, "FollowUpTask not found.", 404)
    return row


def _validate_channels(channels):
    if not isinstance(channels, list) or not channels:
        raise AppError(ERR_REMINDER_CHANNELS_INVALID, "reminder_channels required.", 422)
    for c in channels:
        if c not in VALID_REMINDER_CHANNELS:
            raise AppError(ERR_REMINDER_CHANNELS_INVALID, "invalid channel.", 422)


@bp.post("")
def create_task():
    require_role(ROLE_DOCTOR)
    body = request.get_json(silent=True) or {}
    cid = body.get("consultation_id")
    consultation = db.find_by_id("consultations", cid)
    if not consultation:
        raise AppError(ERR_REF_NOT_FOUND, "consultation_id not found.", 422)
    if g.user_id != consultation.get("doctor_id"):
        raise AppError(ERR_FORBIDDEN, "Only the attending doctor may create.", 403)
    channels = body.get("reminder_channels") or []
    _validate_channels(channels)
    record = {
        "consultation_id": cid,
        "patient_id": consultation.get("patient_id"),
        "plan_template_code": body.get("plan_template_code"),
        "scheduled_reminder_at": body.get("scheduled_reminder_at"),
        "reminder_channels": channels,
        "form_payload": None,
        "abnormal_flag": False,
        "status": "PLANNED",
        "escalation_consultation_id": None,
    }
    row = db.insert("follow_up_tasks", record)
    return success(serialize(row), 201)


@bp.post("/<tid>/fire-reminder")
def fire_reminder(tid):
    require_role(ROLE_ADMIN)
    row = _task_or_404(tid)
    body = request.get_json(silent=True) or {}
    if row.get("status") != "PLANNED":
        raise AppError(ERR_INVALID_STATE, "Not in PLANNED.", 409)
    check_version(row, body)
    scheduled = row.get("scheduled_reminder_at")
    if scheduled:
        try:
            sched_dt = db.parse_iso(scheduled)
        except Exception:
            sched_dt = None
        if sched_dt and db.now_dt() < sched_dt:
            raise AppError(ERR_INVALID_STATE, "Scheduled instant not yet reached.", 409)
    row = db.update("follow_up_tasks", tid, {"status": "REMINDED"})
    return success(serialize(row), 200)


def _compute_abnormal(form_payload) -> bool:
    """True iff any field in form_payload carries a severity >= ABNORMAL_THRESHOLD.

    PRD §3.8 wording: 'any field inside form_payload carries a severity
    equal to or greater than the abnormal threshold'. Treated permissively:
    a top-level `severity` numeric field counts, AND a nested dict's
    `severity` field counts.
    """
    if not isinstance(form_payload, dict):
        return False
    for k, v in form_payload.items():
        if k == "severity" and isinstance(v, (int, float)):
            if v >= ABNORMAL_THRESHOLD:
                return True
        if isinstance(v, dict):
            sev = v.get("severity")
            if isinstance(sev, (int, float)) and sev >= ABNORMAL_THRESHOLD:
                return True
    return False


@bp.post("/<tid>/submit-form")
def submit_form(tid):
    require_role(ROLE_PATIENT)
    row = _task_or_404(tid)
    body = request.get_json(silent=True) or {}
    if g.user_id != row.get("patient_id"):
        raise AppError(ERR_FORBIDDEN, "Not the owner.", 403)
    if row.get("status") != "REMINDED":
        raise AppError(ERR_INVALID_STATE, "Not in REMINDED.", 409)
    check_version(row, body)
    form = body.get("form_payload")
    if form is None:
        raise AppError(ERR_INVALID_STATE, "form_payload required.", 409)
    abnormal = _compute_abnormal(form)
    # transition to SUBMITTED then auto-transition
    updates = {
        "status": "SUBMITTED",
        "form_payload": form,
        "abnormal_flag": abnormal,
    }
    db.update("follow_up_tasks", tid, updates)
    if abnormal:
        # Create a new Consultation (REAL_TIME) for the same patient with same doctor
        consultation = db.find_by_id("consultations", row.get("consultation_id"))
        doctor_id = consultation.get("doctor_id") if consultation else None
        new_record = {
            "triage_session_id": consultation.get("triage_session_id") if consultation else None,
            "patient_id": row.get("patient_id"),
            "doctor_id": doctor_id,
            "mode": "REAL_TIME",
            "scheduled_start_at": None,
            "queue_position": None,
            "media_type": (consultation or {}).get("media_type") or "TEXT_IMAGE",
            "session_status": "PENDING",
            "quality_status": "NOT_APPLICABLE",
            "started_at": None,
            "ended_at": None,
            "duration_minutes": 0,
            "image_attachment_ids": [],
            "transcript_archive_id": None,
            "base_fee": 0,
            "total_fee": 0,
            "transfer_to_doctor_id": None,
        }
        new_consult = db.insert("consultations", new_record)
        row = db.update("follow_up_tasks", tid, {
            "status": "ESCALATED",
            "escalation_consultation_id": new_consult["id"],
        })
        append_audit("FOLLOWUP_ESCALATED", "FollowUpTask", tid, body)
    else:
        row = db.update("follow_up_tasks", tid, {"status": "CLOSED"})
    return success(serialize(row), 200)


@bp.get("/<tid>")
def get_task(tid):
    require_role(ROLE_DOCTOR, ROLE_PATIENT, ROLE_ADMIN)
    row = _task_or_404(tid)
    if g.role == ROLE_PATIENT and g.user_id != row.get("patient_id"):
        raise AppError(ERR_FORBIDDEN, "Not the owner.", 403)
    # Doctor scope check: only the consultation's doctor may access
    if g.role == ROLE_DOCTOR:
        consultation = db.find_by_id("consultations", row.get("consultation_id"))
        if not consultation or g.user_id != consultation.get("doctor_id"):
            raise AppError(ERR_FORBIDDEN, "Not the assigned doctor.", 403)
    return success(serialize(row), 200)
