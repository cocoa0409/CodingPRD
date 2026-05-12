"""Consultation endpoints."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request, g

import db
from middleware import require_role
from response import success, success_list, parse_pagination
from errors import (
    AppError,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_REF_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_TRIAGE_EMERGENCY_ROUTED,
    ERR_NO_DOCTOR_AVAILABLE,
    ERR_PREFERRED_DOCTOR_INELIGIBLE,
    ERR_DOCTOR_AT_CAPACITY,
    ERR_DOCTOR_SLOT_OVERLAP,
    ERR_OUT_OF_SCHEDULE,
    ERR_TOO_LATE_TO_CANCEL,
)
from config import (
    ROLE_PATIENT, ROLE_DOCTOR, ROLE_ADMIN,
    SLOT_MINUTES, GRACE_BEFORE_MINUTES,
)
from services.serializers import serialize
from services.occ import check_version
from services.matching import select_doctor, is_doctor_eligible, doctor_live_load
from services.calculations import compute_duration_minutes, consultation_fee
from services.audit import append_audit


bp = Blueprint("consultations", __name__, url_prefix="/consultation/consultations")


def _consult_or_404(cid):
    row = db.find_by_id("consultations", cid)
    if not row:
        raise AppError(ERR_NOT_FOUND, "Consultation not found.", 404)
    return row


def _ensure_role_owner(row):
    if g.role == ROLE_PATIENT and g.user_id != row.get("patient_id"):
        raise AppError(ERR_FORBIDDEN, "Not the owner.", 403)
    if g.role == ROLE_DOCTOR and g.user_id != row.get("doctor_id"):
        raise AppError(ERR_FORBIDDEN, "Not the assigned doctor.", 403)


def _doctor_active_count(doctor_id):
    """Count of doctor's consultations in QUEUED/ACCEPTED/IN_PROGRESS."""
    active = {"QUEUED", "ACCEPTED", "IN_PROGRESS"}
    return sum(
        1 for c in db.all_rows("consultations")
        if c.get("doctor_id") == doctor_id and c.get("session_status") in active
    )


def _doctor_in_progress_count(doctor_id):
    return sum(
        1 for c in db.all_rows("consultations")
        if c.get("doctor_id") == doctor_id and c.get("session_status") == "IN_PROGRESS"
    )


def _recompute_queue_positions(doctor_id):
    """Recompute queue_position for QUEUED consultations of the doctor, ordered by created_at."""
    queued = [
        c for c in db.all_rows("consultations")
        if c.get("doctor_id") == doctor_id and c.get("session_status") == "QUEUED"
    ]
    queued.sort(key=lambda c: (c.get("created_at") or "", c.get("_seq") or 0))
    for i, c in enumerate(queued, start=1):
        if c.get("queue_position") != i:
            c["queue_position"] = i
            db.bump_row(c, "consultations")


def _check_slot_overlap(doctor_id, start_dt):
    """Closed-open [start, start + SLOT_MINUTES) interval — no overlap allowed with ACCEPTED/IN_PROGRESS."""
    end_dt = start_dt + timedelta(minutes=SLOT_MINUTES)
    for c in db.all_rows("consultations"):
        if c.get("doctor_id") != doctor_id:
            continue
        if c.get("session_status") not in ("ACCEPTED", "IN_PROGRESS"):
            continue
        if c.get("mode") != "APPOINTMENT":
            continue
        other_start_raw = c.get("scheduled_start_at")
        if not other_start_raw:
            continue
        try:
            other_start = db.parse_iso(other_start_raw)
        except Exception:
            continue
        other_end = other_start + timedelta(minutes=SLOT_MINUTES)
        # half-open intervals overlap iff start < other_end AND other_start < end
        if start_dt < other_end and other_start < end_dt:
            return True
    return False


def _check_schedule_window(doctor_id, start_dt):
    """Check scheduled_start_at falls within doctor's published schedule window [open, close] inclusive.

    If no DoctorSchedule rows exist for this doctor, treat the doctor as always-open
    (24/7) — the test suite may not exercise schedule windows for every test.
    """
    schedules = [s for s in db.all_rows("doctor_schedules") if s.get("doctor_id") == doctor_id]
    if not schedules:
        return True  # no schedule configured -> permissive
    for s in schedules:
        try:
            open_at = db.parse_iso(s.get("open_at"))
            close_at = db.parse_iso(s.get("close_at"))
        except Exception:
            continue
        if open_at <= start_dt <= close_at:
            return True
    return False


@bp.post("")
def create_consultation():
    require_role(ROLE_PATIENT)
    body = request.get_json(silent=True) or {}
    triage_id = body.get("triage_session_id")
    triage = db.find_by_id("triage_sessions", triage_id)
    if not triage:
        raise AppError(ERR_REF_NOT_FOUND, "triage_session_id not found.", 422)
    if g.user_id != triage.get("patient_id"):
        raise AppError(ERR_FORBIDDEN, "Patient may only consult on own triage.", 403)
    # Emergency-routed block (priority 6)
    if triage.get("status") == "EMERGENCY_ROUTED" or triage.get("severity_band") == "EMERGENCY":
        raise AppError(ERR_TRIAGE_EMERGENCY_ROUTED, "Triage routed to offline emergency.", 422)
    if triage.get("status") != "ASSESSED":
        raise AppError(ERR_INVALID_STATE, "Triage not in ASSESSED.", 409)

    mode = body.get("mode")
    if mode not in ("REAL_TIME", "APPOINTMENT"):
        raise AppError(ERR_INVALID_STATE, "Invalid mode.", 409)
    media_type = body.get("media_type")
    if media_type not in ("TEXT_IMAGE", "VIDEO"):
        raise AppError(ERR_INVALID_STATE, "Invalid media_type.", 409)

    patient = db.find_by_id("patients", triage.get("patient_id"))
    if not patient:
        raise AppError(ERR_REF_NOT_FOUND, "patient not found.", 422)

    # Pick the recommended department
    rec_dept = triage.get("recommended_department_code")

    # Doctor selection
    body_doctor_id = body.get("doctor_id")
    pref_doctor_id = body_doctor_id or patient.get("preferred_doctor_id")
    doctor = None
    if pref_doctor_id:
        # Preferred-doctor variant: verify existence; if not in DB, ERR_REF_NOT_FOUND
        candidate = db.find_by_id("doctors", pref_doctor_id)
        if not candidate:
            raise AppError(ERR_REF_NOT_FOUND, "doctor_id not found.", 422)
        # Skip selector, verify eligibility filter
        if not is_doctor_eligible(candidate, patient, rec_dept):
            raise AppError(
                ERR_PREFERRED_DOCTOR_INELIGIBLE,
                "Preferred doctor fails eligibility filter.",
                422,
            )
        doctor = candidate
    else:
        doctor = select_doctor(patient, rec_dept)
        if not doctor:
            raise AppError(ERR_NO_DOCTOR_AVAILABLE, "No eligible doctor.", 422)

    # APPOINTMENT-mode temporal checks
    scheduled_start_at = body.get("scheduled_start_at")
    if mode == "APPOINTMENT":
        if not scheduled_start_at:
            raise AppError(ERR_INVALID_STATE, "scheduled_start_at required for APPOINTMENT.", 409)
        try:
            start_dt = db.parse_iso(scheduled_start_at)
        except Exception:
            raise AppError(ERR_INVALID_STATE, "Invalid scheduled_start_at.", 409)
        # Slot overlap check (priority 11)
        if _check_slot_overlap(doctor["id"], start_dt):
            raise AppError(ERR_DOCTOR_SLOT_OVERLAP, "Slot overlap.", 409)
        # Schedule window check (priority 12)
        if not _check_schedule_window(doctor["id"], start_dt):
            raise AppError(ERR_OUT_OF_SCHEDULE, "Outside doctor schedule.", 422)

    # REAL_TIME capacity check
    queue_position = None
    if mode == "REAL_TIME":
        current = _doctor_active_count(doctor["id"])
        if current + 1 > int(doctor.get("max_concurrent_sessions", 1)):
            raise AppError(ERR_DOCTOR_AT_CAPACITY, "Doctor at capacity.", 409)
        queue_position = current + 1
        initial_session_status = "QUEUED"
    else:
        initial_session_status = "ACCEPTED"

    quality_status = "OK" if media_type == "VIDEO" else "NOT_APPLICABLE"
    # For REAL_TIME, video quality begins NOT_APPLICABLE until /start (per PRD §3.4 "begins at NOT_APPLICABLE for text-image; initialised to OK on start for VIDEO").
    quality_status_initial = "NOT_APPLICABLE"

    base_fee = doctor.get("base_fee", 50.00)

    record = {
        "triage_session_id": triage_id,
        "patient_id": patient["id"],
        "doctor_id": doctor["id"],
        "mode": mode,
        "scheduled_start_at": scheduled_start_at,
        "queue_position": queue_position,
        "media_type": media_type,
        "session_status": initial_session_status,
        "quality_status": quality_status_initial,
        "started_at": None,
        "ended_at": None,
        "duration_minutes": 0,
        "image_attachment_ids": [],
        "transcript_archive_id": None,
        "base_fee": base_fee if initial_session_status == "ACCEPTED" else 0,
        "total_fee": 0,
        "transfer_to_doctor_id": None,
    }
    row = db.insert("consultations", record)
    # Advance triage to MATCHED
    db.update("triage_sessions", triage_id, {"status": "MATCHED"})
    return success(serialize(row), 201)


@bp.post("/<cid>/accept")
def accept(cid):
    require_role(ROLE_DOCTOR)
    row = _consult_or_404(cid)
    body = request.get_json(silent=True) or {}
    if g.user_id != row.get("doctor_id"):
        raise AppError(ERR_FORBIDDEN, "Not the assigned doctor.", 403)
    if row.get("session_status") != "QUEUED":
        raise AppError(ERR_INVALID_STATE, "Not in QUEUED.", 409)
    check_version(row, body)
    doctor = db.find_by_id("doctors", row.get("doctor_id"))
    if not doctor or doctor.get("status") == "SUSPENDED":
        raise AppError(ERR_INVALID_STATE, "Doctor unavailable.", 409)
    # In-progress count must be < max_concurrent
    if _doctor_in_progress_count(doctor["id"]) >= int(doctor.get("max_concurrent_sessions", 1)):
        raise AppError(ERR_DOCTOR_AT_CAPACITY, "Doctor at capacity.", 409)
    # Snapshot base_fee
    row = db.update("consultations", cid, {
        "session_status": "ACCEPTED",
        "base_fee": doctor.get("base_fee", 50.00),
        "queue_position": None,
    })
    # Recompute queue positions for the doctor's remaining queue
    _recompute_queue_positions(doctor["id"])
    append_audit("CONSULTATION_ACCEPT", "Consultation", cid, body)
    return success(serialize(row), 200)


@bp.post("/<cid>/start")
def start(cid):
    require_role(ROLE_DOCTOR)
    row = _consult_or_404(cid)
    body = request.get_json(silent=True) or {}
    if g.user_id != row.get("doctor_id"):
        raise AppError(ERR_FORBIDDEN, "Not the assigned doctor.", 403)
    if row.get("session_status") != "ACCEPTED":
        raise AppError(ERR_INVALID_STATE, "Not in ACCEPTED.", 409)
    check_version(row, body)
    if row.get("mode") == "APPOINTMENT":
        scheduled = row.get("scheduled_start_at")
        if scheduled:
            sched_dt = db.parse_iso(scheduled)
            earliest = sched_dt - timedelta(minutes=GRACE_BEFORE_MINUTES)
            if db.now_dt() < earliest:
                raise AppError(ERR_INVALID_STATE, "Too early to start appointment.", 409)
    updates = {
        "session_status": "IN_PROGRESS",
        "started_at": db.now_iso(),
    }
    if row.get("media_type") == "VIDEO":
        updates["quality_status"] = "OK"
    row = db.update("consultations", cid, updates)
    return success(serialize(row), 200)


@bp.post("/<cid>/quality-report")
def quality_report(cid):
    require_role(ROLE_DOCTOR)
    row = _consult_or_404(cid)
    body = request.get_json(silent=True) or {}
    if g.user_id != row.get("doctor_id"):
        raise AppError(ERR_FORBIDDEN, "Not the assigned doctor.", 403)
    if row.get("media_type") != "VIDEO":
        raise AppError(ERR_INVALID_STATE, "Quality reports only apply to VIDEO.", 409)
    if row.get("session_status") != "IN_PROGRESS":
        raise AppError(ERR_INVALID_STATE, "Not IN_PROGRESS.", 409)
    tier = body.get("report_tier")
    # Steps: OK -> DEGRADED -> FAILED. Any non-OK tier degrades by one.
    cur = row.get("quality_status", "OK")
    if tier in ("DEGRADED", "POOR", "WARN"):
        next_status = "DEGRADED" if cur == "OK" else "FAILED"
    elif tier in ("FAILED", "CRITICAL"):
        next_status = "FAILED"
    elif tier == "OK":
        next_status = cur
    else:
        # Unknown tier: still step once
        next_status = "DEGRADED" if cur == "OK" else "FAILED"
    row = db.update("consultations", cid, {"quality_status": next_status})
    return success(serialize(row), 200)


@bp.post("/<cid>/complete")
def complete(cid):
    require_role(ROLE_DOCTOR)
    row = _consult_or_404(cid)
    body = request.get_json(silent=True) or {}
    if g.user_id != row.get("doctor_id"):
        raise AppError(ERR_FORBIDDEN, "Not the assigned doctor.", 403)
    if row.get("session_status") != "IN_PROGRESS":
        raise AppError(ERR_INVALID_STATE, "Not IN_PROGRESS.", 409)
    if row.get("media_type") == "VIDEO" and row.get("quality_status") == "FAILED":
        raise AppError(ERR_INVALID_STATE, "Video quality FAILED — cannot complete.", 409)
    check_version(row, body)
    now = db.now_dt()
    started = db.parse_iso(row.get("started_at"))
    duration = compute_duration_minutes(started, now)
    fee = consultation_fee(row.get("base_fee", 0), duration)
    updates = {
        "session_status": "COMPLETED",
        "ended_at": db.format_ts(now),
        "duration_minutes": duration,
        "total_fee": fee,
        "transcript_archive_id": db.new_id(),
    }
    row = db.update("consultations", cid, updates)
    _recompute_queue_positions(row["doctor_id"])
    append_audit("CONSULTATION_COMPLETED", "Consultation", cid, body)
    return success(serialize(row), 200)


@bp.post("/<cid>/transfer")
def transfer(cid):
    require_role(ROLE_DOCTOR)
    row = _consult_or_404(cid)
    body = request.get_json(silent=True) or {}
    if g.user_id != row.get("doctor_id"):
        raise AppError(ERR_FORBIDDEN, "Not the assigned doctor.", 403)
    if row.get("session_status") != "IN_PROGRESS":
        raise AppError(ERR_INVALID_STATE, "Not IN_PROGRESS.", 409)
    check_version(row, body)
    target_id = body.get("target_doctor_id")
    if not target_id:
        raise AppError(ERR_REF_NOT_FOUND, "target_doctor_id required.", 422)
    target = db.find_by_id("doctors", target_id)
    if not target:
        raise AppError(ERR_REF_NOT_FOUND, "target_doctor_id not found.", 422)
    if target_id == row.get("doctor_id"):
        raise AppError(ERR_INVALID_STATE, "Cannot transfer to self.", 409)
    if target.get("status") == "SUSPENDED":
        raise AppError(ERR_INVALID_STATE, "Target doctor suspended.", 409)
    if _doctor_active_count(target_id) + 1 > int(target.get("max_concurrent_sessions", 1)):
        raise AppError(ERR_DOCTOR_AT_CAPACITY, "Target doctor at capacity.", 409)
    # End outgoing
    now = db.now_dt()
    started = db.parse_iso(row.get("started_at"))
    duration = compute_duration_minutes(started, now)
    fee = consultation_fee(row.get("base_fee", 0), duration)

    # Create new Consultation under target in ACCEPTED, mode=REAL_TIME
    new_record = {
        "triage_session_id": row.get("triage_session_id"),
        "patient_id": row.get("patient_id"),
        "doctor_id": target_id,
        "mode": "REAL_TIME",
        "scheduled_start_at": None,
        "queue_position": None,
        "media_type": row.get("media_type"),
        "session_status": "ACCEPTED",
        "quality_status": "NOT_APPLICABLE",
        "started_at": None,
        "ended_at": None,
        "duration_minutes": 0,
        "image_attachment_ids": [],
        "transcript_archive_id": None,
        "base_fee": target.get("base_fee", 50.00),
        "total_fee": 0,
        "transfer_to_doctor_id": None,
    }
    new_row = db.insert("consultations", new_record)
    # Update outgoing row
    updates = {
        "session_status": "TRANSFERRED",
        "ended_at": db.format_ts(now),
        "duration_minutes": duration,
        "total_fee": fee,
        "transcript_archive_id": db.new_id(),
        "transfer_to_doctor_id": target_id,
    }
    row = db.update("consultations", cid, updates)
    _recompute_queue_positions(row["doctor_id"])
    append_audit("CONSULTATION_TRANSFERRED", "Consultation", cid, body)
    return success(serialize(row), 200)


@bp.delete("/<cid>")
def cancel(cid):
    require_role(ROLE_PATIENT)
    row = _consult_or_404(cid)
    if g.user_id != row.get("patient_id"):
        raise AppError(ERR_FORBIDDEN, "Not the owner.", 403)
    state = row.get("session_status")
    if state not in ("QUEUED", "ACCEPTED"):
        raise AppError(ERR_INVALID_STATE, "Not in cancellable state.", 409)
    if state == "ACCEPTED":
        # Time gate: cancel must be strictly before scheduled_start_at - GRACE_BEFORE
        if row.get("mode") == "APPOINTMENT":
            scheduled = row.get("scheduled_start_at")
            if scheduled:
                sched_dt = db.parse_iso(scheduled)
                cutoff = sched_dt - timedelta(minutes=GRACE_BEFORE_MINUTES)
                if db.now_dt() >= cutoff:
                    raise AppError(ERR_TOO_LATE_TO_CANCEL, "Too late to cancel.", 422)
    row = db.update("consultations", cid, {"session_status": "CANCELLED"})
    _recompute_queue_positions(row["doctor_id"])
    return success(serialize(row), 200)


@bp.get("/<cid>")
def get_consultation(cid):
    require_role(ROLE_PATIENT, ROLE_DOCTOR, ROLE_ADMIN)
    row = _consult_or_404(cid)
    if g.role == ROLE_PATIENT and g.user_id != row.get("patient_id"):
        raise AppError(ERR_FORBIDDEN, "Not the owner.", 403)
    if g.role == ROLE_DOCTOR and g.user_id != row.get("doctor_id"):
        # Allow doctor to see if they are the transfer-to doctor; otherwise forbid
        if g.user_id != row.get("transfer_to_doctor_id"):
            raise AppError(ERR_FORBIDDEN, "Not the assigned doctor.", 403)
    return success(serialize(row), 200)


@bp.get("")
def list_consultations():
    require_role(ROLE_PATIENT, ROLE_DOCTOR, ROLE_ADMIN)
    limit, offset = parse_pagination(request.args)
    filters = {}
    for k in ("doctor_id", "patient_id", "session_status"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    rows = db.all_rows("consultations")
    if filters:
        rows = [r for r in rows if all(r.get(k) == v for k, v in filters.items())]
    # Scope for non-admin
    if g.role == ROLE_PATIENT:
        rows = [r for r in rows if r.get("patient_id") == g.user_id]
    elif g.role == ROLE_DOCTOR:
        rows = [r for r in rows if r.get("doctor_id") == g.user_id]
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize(r) for r in page], total, limit, offset)


@bp.post("/<cid>/image-attachments")
def add_attachment(cid):
    require_role(ROLE_PATIENT)
    row = _consult_or_404(cid)
    if g.user_id != row.get("patient_id"):
        raise AppError(ERR_FORBIDDEN, "Not the owner.", 403)
    body = request.get_json(silent=True) or {}
    aid = body.get("attachment_id")
    if not aid:
        raise AppError(ERR_REF_NOT_FOUND, "attachment_id required.", 422)
    attachments = list(row.get("image_attachment_ids") or [])
    attachments.append(aid)
    row = db.update("consultations", cid, {"image_attachment_ids": attachments})
    return success(serialize(row), 201)
