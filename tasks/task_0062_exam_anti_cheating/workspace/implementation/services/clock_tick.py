"""Drive every automatic, time-gated transition up to the current clock instant.

Called from POST /_clock/advance after the logical clock has been advanced.
"""
import db
from clock import now_unix
from services.audit import append_audit
from services import scoring


def _force_submit_attempts(exam: dict) -> None:
    """Forced submission at end_time: every ACTIVE/SUSPENDED attempt is forced
    to SUBMITTED; objective auto-graded; subjective rows created."""
    from services.attempt import perform_submit  # local import to avoid cycle
    end_time = int(exam.get("end_time"))
    for att in list(db.attempts.values()):
        if att.get("exam_id") != exam["id"]:
            continue
        if att.get("status") not in ("ACTIVE", "SUSPENDED"):
            continue
        # Perform the same logic as candidate submit, but stamp submitted_at at
        # end_time and emit a FORCED_SUBMIT audit row.
        perform_submit(att, submitted_at_unix=end_time, forced=True)


def tick_exam(exam: dict) -> None:
    """Apply every applicable automatic transition for this exam up to now()."""
    now = now_unix()

    # DRAFT / OPEN_REGISTRATION / READY -> IN_SESSION when now >= start_time.
    # Per PRD §3.2: 'Only when the clock reaches start_time may a Candidate open
    # an attempt'; this requires the exam transition to fire. We only fire from
    # READY (paper composition prerequisite).
    if exam.get("status") == "READY" and now >= int(exam.get("start_time")):
        exam["status"] = "IN_SESSION"
        db.stamp_update(exam)

    if exam.get("status") == "IN_SESSION" and now >= int(exam.get("end_time")):
        # Forced submit cascade
        _force_submit_attempts(exam)
        exam["status"] = "GRADING"
        # Recompute grading progress after submissions created rows.
        exam["grading_progress_pct"] = scoring.recompute_grading_progress(exam["id"])
        db.stamp_update(exam)

    # SCORES_PUBLISHED → APPEAL_WINDOW (1 second after publish)
    if exam.get("status") == "SCORES_PUBLISHED":
        pub = exam.get("_published_at_unix")
        if pub is not None and now >= int(pub) + 1:
            exam["status"] = "APPEAL_WINDOW"
            db.stamp_update(exam)

    # APPEAL_WINDOW → ARCHIVED (after appeal_window_seconds from publish)
    if exam.get("status") == "APPEAL_WINDOW":
        pub = exam.get("_published_at_unix")
        window = int(exam.get("appeal_window_seconds") or 86400)
        if pub is not None and now >= int(pub) + window:
            # Force-reject all open appeals (no score adjustment, no audit row).
            for ap in db.appeals.values():
                if ap.get("attempt_id") not in {a["id"] for a in db.attempts.values()
                                                if a.get("exam_id") == exam["id"]}:
                    continue
                if ap.get("status") in ("SUBMITTED", "UNDER_REVIEW", "DECISION_PENDING"):
                    ap["status"] = "REJECTED"
                    db.stamp_update(ap)
            exam["status"] = "ARCHIVED"
            db.stamp_update(exam)


def tick_all() -> None:
    """Drive every exam through whatever automatic transitions are now ripe.
    Loop until quiescence in case multiple stage hops happen in one tick."""
    for _ in range(8):  # at most 4 transitions but be safe
        before = [(e["id"], e.get("status")) for e in db.exams.values()]
        for exam in list(db.exams.values()):
            tick_exam(exam)
        after = [(e["id"], e.get("status")) for e in db.exams.values()]
        if before == after:
            break
