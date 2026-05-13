"""Business logic for ExamAttempt transitions: submission, identity, etc."""
import db
from clock import now_unix
from services.audit import append_audit
from services import scoring


SUBJECTIVE_TYPES = {"SHORT_ANSWER", "ESSAY"}


def _create_blind_assignments_for(attempt: dict) -> None:
    """Create two PENDING GradingAssignment rows per subjective question in the
    attempt's paper. candidate_answer_snapshot frozen at creation."""
    answers = attempt.get("_answers") or {}
    for qid in attempt.get("paper_question_ids") or []:
        q = db.questions.get(qid)
        if q is None or q.get("question_type") not in SUBJECTIVE_TYPES:
            continue
        snapshot = answers.get(qid)
        # Always serialize as string for snapshot field per scaffold type.
        if isinstance(snapshot, (dict, list)):
            import json
            snap_str = json.dumps(snapshot, ensure_ascii=False)
        elif snapshot is None:
            snap_str = ""
        else:
            snap_str = str(snapshot)
        for slot in ("BLIND_A", "BLIND_B"):
            row = {
                "attempt_id": attempt["id"],
                "question_id": qid,
                "marker_id": None,
                "blind_slot": slot,
                "candidate_answer_snapshot": snap_str,
                "awarded_points": None,
                "rubric_breakdown": None,
                "status": "PENDING",
            }
            db.stamp_create(row, common_fields=True)
            db.grading_assignments[row["id"]] = row


def perform_submit(attempt: dict, *, submitted_at_unix: int, forced: bool) -> None:
    """Common submission path used by candidate-initiated and forced submit.

    On forced=True an AuditLogEntry with action_code=FORCED_SUBMIT is appended.
    """
    attempt["status"] = "SUBMITTED"
    attempt["submitted_at"] = int(submitted_at_unix)
    db.stamp_update(attempt)

    # Create blind grading rows
    _create_blind_assignments_for(attempt)
    # Recompute scores (objective points are finalisable at submission;
    # subjective is still 0).
    scoring.recompute_attempt_scores(attempt)

    if forced:
        append_audit(
            subject_type="EXAM_ATTEMPT",
            subject_id=attempt["id"],
            actor_role="system",
            actor_id="system",
            action_code="FORCED_SUBMIT",
            delta={
                "before": {"status": "ACTIVE_OR_SUSPENDED"},
                "after": {"status": "SUBMITTED",
                          "submitted_at": int(submitted_at_unix)},
            },
        )

    # If the attempt has no subjective questions at all → auto-transition GRADED.
    scoring.maybe_finalize_attempt(attempt)
