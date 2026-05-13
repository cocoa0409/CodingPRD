"""ExamAttempt endpoints (create/get/begin-identity/verify/disconnect/resume/submit)."""
from __future__ import annotations

from flask import Blueprint, g

import db
from clock import now_unix
from errors import err
from middleware import require_auth, get_json_body
from response import success
from services.util import occ_check
from services.audit import append_audit
from services import paper, cascade, attempt as attempt_svc


bp = Blueprint("attempts", __name__)


def _attempt_view(a: dict) -> dict:
    d = db.public(a)
    # Hide private answers field.
    d.pop("_answers", None)
    d.pop("_appeals_delta", None)
    return d


def _require_exam(exam_id: str) -> dict:
    exam = db.exams.get(exam_id)
    if exam is None:
        raise err("ERR_EXAM_NOT_FOUND", "exam not found")
    return exam


def _require_attempt(exam_id: str, attempt_id: str) -> dict:
    _require_exam(exam_id)
    a = db.attempts.get(attempt_id)
    if a is None or a.get("exam_id") != exam_id:
        raise err("ERR_ATTEMPT_NOT_FOUND", "attempt not found")
    return a


def _check_candidate_owns(attempt: dict) -> None:
    """For role=Candidate, X-User-ID must match the registration's candidate_id."""
    if g.user_role != "Candidate":
        return
    reg = db.registrations.get(attempt.get("registration_id"))
    if reg is None or reg.get("candidate_id") != g.user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "not your attempt")


def _has_outstanding_recheck(attempt_id: str) -> dict | None:
    """Return the most recent CRITICAL AbnormalEvent with forced_recheck_emitted
    for this attempt that has not yet been settled by a later
    IdentityVerificationRecord, or None."""
    events = [
        e for e in db.abnormal_events.values()
        if e.get("attempt_id") == attempt_id
        and e.get("forced_recheck_emitted") is True
    ]
    if not events:
        return None
    events.sort(key=lambda e: e["_seq"])
    last_event = events[-1]
    # Look for an IdentityVerificationRecord with _seq > last_event._seq for this attempt.
    later_rec = [
        r for r in db.identity_records.values()
        if r.get("attempt_id") == attempt_id
        and r["_seq"] > last_event["_seq"]
    ]
    if later_rec:
        return None
    return last_event


@bp.post("/exams/<exam_id>/attempts")
@require_auth(roles={"Candidate"})
def create_attempt(exam_id):
    exam = _require_exam(exam_id)
    if exam.get("status") != "IN_SESSION":
        raise err("ERR_EXAM_NOT_IN_SESSION",
                  f"attempt creation requires IN_SESSION (got {exam.get('status')})")
    body = get_json_body()
    registration_id = body.get("registration_id")
    if not isinstance(registration_id, str) or not registration_id:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "registration_id required")
    reg = db.registrations.get(registration_id)
    if reg is None or reg.get("exam_id") != exam_id:
        raise err("ERR_REGISTRATION_NOT_FOUND", "registration not found")
    # Candidate ownership: X-User-ID must equal registration.candidate_id
    if reg.get("candidate_id") != g.user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "not your registration")
    if reg.get("status") == "DISQUALIFIED":
        raise err("ERR_INVALID_STATE", "registration is DISQUALIFIED")
    # One attempt per registration
    for a in db.attempts.values():
        if a.get("registration_id") == registration_id:
            raise err("ERR_INVALID_STATE", "attempt already exists for this registration")

    a = {
        "exam_id": exam_id,
        "registration_id": registration_id,
        "candidate_id": reg.get("candidate_id"),
        "paper_version_hash": None,
        "paper_question_ids": [],
        "paper_option_order": {},
        "started_at": None,
        "submitted_at": None,
        "suspended_total_seconds": 0,
        "current_suspend_started_at": None,
        "provisional_score": 0.0,
        "final_score": 0.0,
        "identity_verification_count": 0,
        "status": "ENROLLED",
        "_answers": {},
        "_appeals_delta": 0.0,
    }
    db.stamp_create(a, common_fields=True)
    db.attempts[a["id"]] = a
    return success(_attempt_view(a), 201)


@bp.get("/exams/<exam_id>/attempts/<attempt_id>")
@require_auth(roles={"Candidate", "ExamAdmin", "Proctor"})
def get_attempt(exam_id, attempt_id):
    a = _require_attempt(exam_id, attempt_id)
    _check_candidate_owns(a)
    return success(_attempt_view(a))


@bp.post("/exams/<exam_id>/attempts/<attempt_id>/begin-identity-check")
@require_auth(roles={"Candidate"})
def begin_identity_check(exam_id, attempt_id):
    exam = _require_exam(exam_id)
    a = _require_attempt(exam_id, attempt_id)
    _check_candidate_owns(a)
    body = get_json_body()
    if exam.get("status") != "IN_SESSION":
        raise err("ERR_EXAM_NOT_IN_SESSION",
                  f"begin-identity-check requires IN_SESSION (got {exam.get('status')})")
    if a.get("status") != "ENROLLED":
        raise err("ERR_INVALID_STATE",
                  f"begin-identity-check requires ENROLLED (got {a.get('status')})")
    occ_check(a, body)
    a["status"] = "IDENTITY_PENDING"
    db.stamp_update(a)
    return success(_attempt_view(a))


@bp.post("/exams/<exam_id>/attempts/<attempt_id>/identity-verifications")
@require_auth(roles={"Candidate"})
def identity_verifications(exam_id, attempt_id):
    exam = _require_exam(exam_id)
    a = _require_attempt(exam_id, attempt_id)
    _check_candidate_owns(a)
    body = get_json_body()
    phase = body.get("verification_phase")
    factors = body.get("factor_results")
    triggered_by = body.get("triggered_by_event_id")

    if phase not in ("PRE_EXAM", "IN_EXAM_RECHECK"):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  f"invalid verification_phase {phase!r}")
    if not isinstance(factors, dict):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "factor_results required")
    for key in ("id_card", "face", "live_detection"):
        if key not in factors or not isinstance(factors[key], bool):
            raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                      f"factor_results.{key} required and must be bool")
    outcome = "PASS" if all(factors[k] for k in ("id_card", "face", "live_detection")) else "MISMATCH"

    # ---- Validation priority §2.7 ----
    if phase == "PRE_EXAM":
        # state precondition first (priority 5): attempt must be IDENTITY_PENDING
        if a.get("status") != "IDENTITY_PENDING":
            raise err("ERR_INVALID_STATE",
                      f"PRE_EXAM verification requires IDENTITY_PENDING (got {a.get('status')})")
        # exam-state precondition (priority 4) for the success branch:
        if exam.get("status") != "IN_SESSION":
            raise err("ERR_EXAM_NOT_IN_SESSION",
                      "PRE_EXAM verification requires Exam IN_SESSION")
        # Forced-submit override (priority 7) only applies during ACTIVE — N/A here.
        if outcome == "MISMATCH":
            # Priority 6: surface as ERR_IDENTITY_MISMATCH and cascade disqualify.
            rec = _persist_identity_record(a, phase, factors, outcome, triggered_by)
            cascade.disqualify_attempt(
                a,
                actor_role="Candidate",
                actor_id=g.user_id,
                action_code="IDENTITY_MISMATCH",
            )
            # identity_verification_count was incremented in persist.
            raise err("ERR_IDENTITY_MISMATCH", "identity verification failed")
        # PASS path
        rec = _persist_identity_record(a, phase, factors, outcome, triggered_by)
        a["status"] = "ACTIVE"
        a["started_at"] = now_unix()
        # Run paper composition
        qids, opt_order, vhash = paper.compose_paper(exam, a)
        a["paper_question_ids"] = qids
        a["paper_option_order"] = opt_order
        a["paper_version_hash"] = vhash
        db.stamp_update(a)
        return success(db.public(rec), 201)

    # phase == IN_EXAM_RECHECK
    # state precondition: attempt must be ACTIVE
    if a.get("status") != "ACTIVE":
        # If the attempt has already been forced past ACTIVE because of end_time,
        # the window-closed error has priority (§2.7 priority 7) — but we only
        # surface that for ACTIVE-state operations. Here the attempt is no longer
        # ACTIVE so:
        if now_unix() >= int(exam.get("end_time", 0)) and a.get("status") in ("SUBMITTED", "SUSPENDED"):
            raise err("ERR_EXAM_WINDOW_CLOSED", "exam end_time has passed")
        raise err("ERR_INVALID_STATE",
                  f"IN_EXAM_RECHECK requires ACTIVE (got {a.get('status')})")
    # exam-state precondition: still IN_SESSION
    if exam.get("status") != "IN_SESSION":
        raise err("ERR_EXAM_NOT_IN_SESSION",
                  "IN_EXAM_RECHECK requires Exam IN_SESSION")
    # forced-submit override
    if now_unix() >= int(exam.get("end_time", 0)):
        raise err("ERR_EXAM_WINDOW_CLOSED", "exam end_time has passed")
    # Must have a pending forced_recheck event
    pending = _has_outstanding_recheck(attempt_id)
    if pending is None:
        raise err("ERR_NO_PENDING_RECHECK", "no outstanding forced recheck")

    if outcome == "MISMATCH":
        rec = _persist_identity_record(a, phase, factors, outcome, triggered_by)
        cascade.disqualify_attempt(
            a,
            actor_role="Candidate",
            actor_id=g.user_id,
            action_code="IDENTITY_MISMATCH",
        )
        raise err("ERR_IDENTITY_MISMATCH", "identity verification failed")

    # PASS path — self-loop, stays ACTIVE.
    rec = _persist_identity_record(a, phase, factors, outcome, triggered_by)
    db.stamp_update(a)
    return success(db.public(rec), 201)


def _persist_identity_record(attempt: dict, phase: str, factors: dict,
                             outcome: str, triggered_by) -> dict:
    rec = {
        "attempt_id": attempt["id"],
        "verification_phase": phase,
        "factor_results": dict(factors),
        "outcome": outcome,
        "triggered_by_event_id": triggered_by if phase == "IN_EXAM_RECHECK" else None,
    }
    db.stamp_create(rec, common_fields=False)
    db.identity_records[rec["id"]] = rec
    attempt["identity_verification_count"] = int(attempt.get("identity_verification_count", 0)) + 1
    return rec


@bp.post("/exams/<exam_id>/attempts/<attempt_id>/network-disconnect")
@require_auth(roles={"Candidate"})
def network_disconnect(exam_id, attempt_id):
    exam = _require_exam(exam_id)
    a = _require_attempt(exam_id, attempt_id)
    _check_candidate_owns(a)
    body = get_json_body()
    if a.get("status") != "ACTIVE":
        raise err("ERR_INVALID_STATE",
                  f"network-disconnect requires ACTIVE (got {a.get('status')})")
    occ_check(a, body)
    a["status"] = "SUSPENDED"
    a["current_suspend_started_at"] = now_unix()
    db.stamp_update(a)
    return success(_attempt_view(a))


@bp.post("/exams/<exam_id>/attempts/<attempt_id>/network-resume")
@require_auth(roles={"Candidate"})
def network_resume(exam_id, attempt_id):
    exam = _require_exam(exam_id)
    a = _require_attempt(exam_id, attempt_id)
    _check_candidate_owns(a)
    body = get_json_body()
    if a.get("status") != "SUSPENDED":
        raise err("ERR_INVALID_STATE",
                  f"network-resume requires SUSPENDED (got {a.get('status')})")
    if exam.get("status") != "IN_SESSION":
        raise err("ERR_EXAM_NOT_IN_SESSION",
                  "network-resume requires Exam IN_SESSION")
    if now_unix() >= int(exam.get("end_time", 0)):
        raise err("ERR_EXAM_WINDOW_CLOSED", "exam end_time has passed")
    occ_check(a, body)
    start = int(a.get("current_suspend_started_at") or 0)
    elapsed = max(0, now_unix() - start)
    a["suspended_total_seconds"] = int(a.get("suspended_total_seconds", 0)) + elapsed
    a["current_suspend_started_at"] = None
    a["status"] = "ACTIVE"
    db.stamp_update(a)
    return success(_attempt_view(a))


@bp.post("/exams/<exam_id>/attempts/<attempt_id>/submit")
@require_auth(roles={"Candidate"})
def submit_attempt(exam_id, attempt_id):
    exam = _require_exam(exam_id)
    a = _require_attempt(exam_id, attempt_id)
    _check_candidate_owns(a)
    body = get_json_body()
    if a.get("status") != "ACTIVE":
        # Possibly already forced-submitted: surface ERR_INVALID_STATE.
        # If we're past end_time AND status is no longer ACTIVE → ERR_INVALID_STATE
        # (the forced-submit cascade has already fired).
        raise err("ERR_INVALID_STATE",
                  f"submit requires ACTIVE (got {a.get('status')})")
    if exam.get("status") != "IN_SESSION":
        raise err("ERR_EXAM_NOT_IN_SESSION",
                  "submit requires Exam IN_SESSION")
    if now_unix() >= int(exam.get("end_time", 0)):
        raise err("ERR_EXAM_WINDOW_CLOSED", "exam end_time has passed")
    occ_check(a, body)
    # answers payload — optional complete replacement.
    if "answers" in body:
        ans = body["answers"]
        if not isinstance(ans, dict):
            raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                      "answers must be an object keyed by question_id")
        a["_answers"] = dict(ans)

    attempt_svc.perform_submit(a, submitted_at_unix=now_unix(), forced=False)
    return success(_attempt_view(a))
