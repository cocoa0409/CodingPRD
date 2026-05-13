"""Score aggregation: objective auto-grade + subjective per-question round +
grading_progress_pct per PRD §3.6.

Implements provisional_score_calculation, final_score_calculation, and
grading_progress_pct exactly as scaffold §1.3 specifies.
"""
from __future__ import annotations

from decimal import Decimal

import db
from services.util import round_half_up_2dp


OBJECTIVE_TYPES = {"SINGLE_CHOICE", "MULTI_CHOICE", "TRUE_FALSE"}
SUBJECTIVE_TYPES = {"SHORT_ANSWER", "ESSAY"}

ARBITRATION_THRESHOLD = Decimal("2.0")


def _question(qid: str) -> dict | None:
    return db.questions.get(qid)


def _answer_matches(question: dict, candidate_answer) -> bool:
    """Compare candidate's answer to correct_answer per PRD §3.6."""
    correct = question.get("correct_answer") or []
    qtype = question.get("question_type")
    if qtype == "MULTI_CHOICE":
        if not isinstance(candidate_answer, (list, tuple)):
            return False
        return set(candidate_answer) == set(correct)
    if qtype in ("SINGLE_CHOICE", "TRUE_FALSE"):
        # scalar equality. correct is an array — take its sole element.
        if isinstance(correct, (list, tuple)):
            corr_val = correct[0] if correct else None
        else:
            corr_val = correct
        if isinstance(candidate_answer, (list, tuple)):
            cand_val = candidate_answer[0] if candidate_answer else None
        else:
            cand_val = candidate_answer
        return cand_val == corr_val
    return False


def compute_objective_points(attempt: dict) -> float:
    """Exact sum of question.max_points for each correctly-answered objective
    question among paper_question_ids. Returns a float (no rounding)."""
    answers = attempt.get("_answers") or {}
    total = Decimal("0")
    for qid in attempt.get("paper_question_ids") or []:
        q = _question(qid)
        if q is None:
            continue
        if q.get("question_type") not in OBJECTIVE_TYPES:
            continue
        cand = answers.get(qid)
        if cand is None:
            continue
        if _answer_matches(q, cand):
            total += Decimal(str(q.get("max_points", 0)))
    return float(total)


def _resolved_rows_for(attempt_id: str, question_id: str) -> list:
    return [
        r for r in db.grading_assignments.values()
        if r.get("attempt_id") == attempt_id
        and r.get("question_id") == question_id
        and r.get("status") == "RESOLVED"
    ]


def compute_subjective_points(attempt: dict) -> float:
    """Per-question rounded mean / arbitration value, then exact sum.

    Pinned ordering (scaffold §1.3 provisional_score_calculation):
      - per-question value rounded half-up to 2dp
      - sum of per-question values is exact (no further rounding)
    """
    total = Decimal("0")
    for qid in attempt.get("paper_question_ids") or []:
        q = _question(qid)
        if q is None or q.get("question_type") not in SUBJECTIVE_TYPES:
            continue
        rows = _resolved_rows_for(attempt["id"], qid)
        if not rows:
            continue
        # ARBITRATION takes precedence when present
        arb = next((r for r in rows if r.get("blind_slot") == "ARBITRATION"), None)
        if arb is not None:
            per_q = round_half_up_2dp(arb.get("awarded_points", 0))
        else:
            a = next((r for r in rows if r.get("blind_slot") == "BLIND_A"), None)
            b = next((r for r in rows if r.get("blind_slot") == "BLIND_B"), None)
            if a is None or b is None:
                continue
            mean = (Decimal(str(a.get("awarded_points", 0)))
                    + Decimal(str(b.get("awarded_points", 0)))) / Decimal("2")
            per_q = round_half_up_2dp(mean)
        total += Decimal(str(per_q))
    return float(total)


def recompute_attempt_scores(attempt: dict) -> None:
    """Recompute provisional_score and final_score from the current world state
    and the disqualification override. Mutates attempt in place but does NOT
    stamp_update; callers stamp_update themselves so they can batch with other
    mutations on the same attempt."""
    if attempt.get("status") == "DISQUALIFIED":
        attempt["provisional_score"] = 0.0
        attempt["final_score"] = 0.0
        return
    obj_pts = compute_objective_points(attempt)
    subj_pts = compute_subjective_points(attempt)
    total = float(Decimal(str(obj_pts)) + Decimal(str(subj_pts)))
    attempt["provisional_score"] = total
    # final_score is the same value until APPEAL adjustments accumulate.
    # We store an "appeals_delta" on the attempt to support post-appeal final.
    delta = float(attempt.get("_appeals_delta", 0.0))
    attempt["final_score"] = float(Decimal(str(total)) + Decimal(str(delta)))


def recompute_grading_progress(exam_id: str) -> float:
    """100 * done / total over GradingAssignment rows under non-DISQUALIFIED
    attempts of this exam, rounded half-up to 2dp. 100.0 when no slots."""
    relevant = []
    for r in db.grading_assignments.values():
        attempt = db.attempts.get(r.get("attempt_id"))
        if attempt is None or attempt.get("exam_id") != exam_id:
            continue
        if attempt.get("status") == "DISQUALIFIED":
            continue
        relevant.append(r)
    total = len(relevant)
    if total == 0:
        return 100.0
    done = sum(1 for r in relevant if r.get("status") in ("RESOLVED", "DISCARDED"))
    return round_half_up_2dp(Decimal(100) * Decimal(done) / Decimal(total))


def maybe_finalize_attempt(attempt: dict) -> bool:
    """If the attempt is SUBMITTED and every subjective question has all of its
    GradingAssignment rows in RESOLVED or DISCARDED, transition SUBMITTED→GRADED
    and recompute final_score. Returns True if the transition fired."""
    if attempt.get("status") != "SUBMITTED":
        return False
    # Check every GradingAssignment row for this attempt.
    rows = [r for r in db.grading_assignments.values()
            if r.get("attempt_id") == attempt["id"]]
    if not rows:
        # No subjective rows yet: the PRD §3.6 trigger ("Once every
        # GradingAssignment row for the attempt is in RESOLVED or
        # DISCARDED") fires from a row-state event. With zero rows
        # nothing has happened yet — stay SUBMITTED. The attempt will be
        # finalized only when called from a row-state transition (claim
        # / score / arbitration), at which point rows will exist.
        return False
    if all(r.get("status") in ("RESOLVED", "DISCARDED") for r in rows):
        attempt["status"] = "GRADED"
        db.stamp_update(attempt)
        recompute_attempt_scores(attempt)
        return True
    return False
