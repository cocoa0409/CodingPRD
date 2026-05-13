"""GradingAssignment claim/score/arbitrate/resolve logic per PRD §3.6."""
from decimal import Decimal

import db
from services import scoring


ARBITRATION_THRESHOLD = Decimal("2.0")


def siblings(row: dict) -> list:
    """Return all GradingAssignment rows sharing (attempt_id, question_id) with
    this row, EXCLUDING this row itself."""
    return [
        r for r in db.grading_assignments.values()
        if r.get("attempt_id") == row.get("attempt_id")
        and r.get("question_id") == row.get("question_id")
        and r["id"] != row["id"]
    ]


def all_in_pair(attempt_id: str, question_id: str) -> list:
    return [
        r for r in db.grading_assignments.values()
        if r.get("attempt_id") == attempt_id and r.get("question_id") == question_id
    ]


def resolve_pair_if_ready(row: dict) -> None:
    """After a SUBMITTED scoring action, see whether the sibling pair has both
    SUBMITTED rows. If yes: either both → RESOLVED (delta within threshold), or
    spawn an arbitration row (delta exceeds threshold)."""
    pair = all_in_pair(row["attempt_id"], row["question_id"])
    blinds = [r for r in pair if r.get("blind_slot") in ("BLIND_A", "BLIND_B")]
    arb_existing = next((r for r in pair if r.get("blind_slot") == "ARBITRATION"), None)

    # If the arbitration row was just scored to SUBMITTED, resolve all three.
    if row.get("blind_slot") == "ARBITRATION" and row.get("status") == "SUBMITTED":
        # All three rows transition to RESOLVED together.
        row["status"] = "RESOLVED"
        db.stamp_update(row)
        for r in blinds:
            if r.get("status") in ("SUBMITTED",):
                r["status"] = "RESOLVED"
                db.stamp_update(r)
        return

    # Normal blind-pair resolution path.
    if len(blinds) < 2:
        return
    if not all(r.get("status") == "SUBMITTED" for r in blinds):
        return
    if arb_existing is not None:
        # Arbitration already in play; do not change blind state here.
        return

    a = next((r for r in blinds if r.get("blind_slot") == "BLIND_A"), None)
    b = next((r for r in blinds if r.get("blind_slot") == "BLIND_B"), None)
    if a is None or b is None:
        return
    delta = abs(Decimal(str(a.get("awarded_points", 0)))
                - Decimal(str(b.get("awarded_points", 0))))
    if delta <= ARBITRATION_THRESHOLD:
        a["status"] = "RESOLVED"
        b["status"] = "RESOLVED"
        db.stamp_update(a)
        db.stamp_update(b)
    else:
        # Spawn a third ARBITRATION row in PENDING. The two SUBMITTED rows stay
        # SUBMITTED until the arbitrator scores their row.
        arb = {
            "attempt_id": row["attempt_id"],
            "question_id": row["question_id"],
            "marker_id": None,
            "blind_slot": "ARBITRATION",
            "candidate_answer_snapshot": a.get("candidate_answer_snapshot"),
            "awarded_points": None,
            "rubric_breakdown": None,
            "status": "PENDING",
        }
        db.stamp_create(arb, common_fields=True)
        db.grading_assignments[arb["id"]] = arb


def double_blind_conflict(attempt_id: str, question_id: str, marker_id: str) -> bool:
    """True if `marker_id` has previously claimed any GradingAssignment for the
    same (attempt_id, question_id) pair. Preserves double-blind invariant."""
    for r in db.grading_assignments.values():
        if (r.get("attempt_id") == attempt_id
                and r.get("question_id") == question_id
                and r.get("marker_id") == marker_id):
            return True
    return False


def post_score_recompute(row: dict) -> None:
    """After a scoring/resolution action, recompute provisional/final scores on
    the attempt and grading_progress_pct on the exam, then maybe-finalize."""
    attempt = db.attempts.get(row.get("attempt_id"))
    if attempt is None:
        return
    scoring.recompute_attempt_scores(attempt)
    db.stamp_update(attempt)

    exam = db.exams.get(attempt.get("exam_id"))
    if exam is not None:
        exam["grading_progress_pct"] = scoring.recompute_grading_progress(exam["id"])
        db.stamp_update(exam)

    # If all rows for the attempt are now RESOLVED/DISCARDED, transition GRADED.
    scoring.maybe_finalize_attempt(attempt)

    # After potential GRADED transition, refresh progress once more.
    if exam is not None:
        exam["grading_progress_pct"] = scoring.recompute_grading_progress(exam["id"])
        db.stamp_update(exam)
