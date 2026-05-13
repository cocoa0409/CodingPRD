"""Cross-aggregate cascade helpers (DISQUALIFIED, progress recompute, etc.)."""
import db
from services.audit import append_audit
from services import scoring


def disqualify_attempt(attempt: dict, *, actor_role: str, actor_id: str,
                       action_code: str, write_audit: bool = True) -> None:
    """Cascade an ExamAttempt to DISQUALIFIED. The PRD specifies:
      - CandidateRegistration.status → DISQUALIFIED
      - All PENDING/IN_PROGRESS GradingAssignment for the attempt → DISCARDED
      - final_score, provisional_score forced to 0
      - Exam.grading_progress_pct recomputed
      - AuditLogEntry appended (action_code as supplied)

    Idempotent: if the attempt is already DISQUALIFIED, no-op (but the second
    cascade attempt is what surfaces ERR_INVALID_STATE — that's a check at the
    caller, not here)."""
    if attempt.get("status") == "DISQUALIFIED":
        return

    prior_final = attempt.get("final_score")
    prior_prov = attempt.get("provisional_score")

    attempt["status"] = "DISQUALIFIED"
    attempt["final_score"] = 0.0
    attempt["provisional_score"] = 0.0
    db.stamp_update(attempt)

    # Cascade registration
    reg = db.registrations.get(attempt.get("registration_id"))
    if reg is not None and reg.get("status") != "DISQUALIFIED":
        reg["status"] = "DISQUALIFIED"
        db.stamp_update(reg)

    # Cascade GradingAssignments
    for r in list(db.grading_assignments.values()):
        if r.get("attempt_id") != attempt["id"]:
            continue
        if r.get("status") in ("PENDING", "IN_PROGRESS"):
            r["status"] = "DISCARDED"
            db.stamp_update(r)

    # Recompute exam grading progress
    exam = db.exams.get(attempt.get("exam_id"))
    if exam is not None:
        exam["grading_progress_pct"] = scoring.recompute_grading_progress(exam["id"])
        db.stamp_update(exam)

    if write_audit:
        append_audit(
            subject_type="EXAM_ATTEMPT",
            subject_id=attempt["id"],
            actor_role=actor_role,
            actor_id=actor_id,
            action_code=action_code,
            delta={
                "before": {"final_score": prior_final,
                           "provisional_score": prior_prov,
                           "status": "ACTIVE"},
                "after": {"final_score": 0,
                          "provisional_score": 0,
                          "status": "DISQUALIFIED"},
            },
        )
