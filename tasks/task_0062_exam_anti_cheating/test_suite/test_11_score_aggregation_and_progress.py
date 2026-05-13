"""Score aggregation and grading_progress_pct.

Covers PRD §3.6 — provisional vs final score, round-per-question
discipline, subjective summation, grading_progress_pct formula.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    attempt_submitted,
    exam_ready_for_candidates,
    list_grading_rows_for_pair,
    make_candidate_headers,
    make_marker_headers,
    resolve_subjective_question,
    score_grading_payload,
    validate_success,
)


def test_provisional_score_unresolved_subjective_treated_as_zero(api):
    """PRD §3.6: "Rows in PENDING, IN_PROGRESS, SUBMITTED, or DISCARDED
    are excluded from this calculation; their existence is the source
    of the gap between provisional and final scores during the GRADING
    phase. The provisional variant treats unresolved questions as zero
    and is therefore an underestimate."

    Difficulty design: dual_variant_calc /
    provisional_vs_final_score_on_exam_attempt (part A — only one
    blind has been scored).
    """
    # difficulty: dual_variant_calc/provisional_vs_final_score_on_exam_attempt
    exam, obj_qs, subj_qs = exam_ready_for_candidates(
        start_time=1000, end_time=10_000,
        num_objective=1, num_subjective=1,
        objective_max_points=20, subjective_max_points=10,
        sampling_rule_spec={"target_count": 2},
    )
    obj_q = obj_qs[0]
    subj_q = subj_qs[0]
    reg, attempt, cid = attempt_submitted(
        exam, obj_qs, subj_qs,
        answers={obj_q["id"]: obj_q["correct_answer"],
                 subj_q["id"]: "free-form"},
    )
    # No subjective grading yet → provisional_score == objective only (20.00).
    refreshed = validate_success(
        api.get_attempt(
            exam["id"], attempt["id"], make_candidate_headers(cid),
        ), 200,
    )
    assert refreshed["provisional_score"] == pytest.approx(20.00, abs=0.01)

    # Score only BLIND_A (sibling still PENDING/IN_PROGRESS) — provisional
    # still excludes the unresolved subjective.
    rows = list_grading_rows_for_pair(exam["id"], attempt["id"], subj_q["id"])
    blind_a = next(r for r in rows if r["blind_slot"] == "BLIND_A")
    m1 = make_marker_headers("m1-partial")
    validate_success(
        api.claim_grading_assignment(exam["id"], blind_a["id"], m1), 200,
    )
    validate_success(
        api.score_grading_assignment(
            exam["id"], blind_a["id"], score_grading_payload(8.0), m1,
        ), 200,
    )
    mid = validate_success(
        api.get_attempt(
            exam["id"], attempt["id"], make_candidate_headers(cid),
        ), 200,
    )
    # PRD §3.6: BLIND_A SUBMITTED but BLIND_B still PENDING → no
    # RESOLVED rows for this question → subjective contribution = 0.
    assert mid["provisional_score"] == pytest.approx(20.00, abs=0.01), (
        "provisional_score must remain 20.00 (objective only) until the "
        "blind pair RESOLVES (PRD §3.6 excludes SUBMITTED rows from the "
        "aggregation)."
    )

    # Resolve both blinds (|delta|=1 ≤ 2.0): subjective per-question
    # mean = round((8+7)/2, 2) = 7.50 → provisional = 20 + 7.50 = 27.50.
    blind_b = next(r for r in rows if r["blind_slot"] == "BLIND_B")
    m2 = make_marker_headers("m2-partial")
    validate_success(
        api.claim_grading_assignment(exam["id"], blind_b["id"], m2), 200,
    )
    validate_success(
        api.score_grading_assignment(
            exam["id"], blind_b["id"], score_grading_payload(7.0), m2,
        ), 200,
    )
    final = validate_success(
        api.get_attempt(
            exam["id"], attempt["id"], make_candidate_headers(cid),
        ), 200,
    )
    assert final["provisional_score"] == pytest.approx(27.50, abs=0.01)


def test_round_per_question_then_sum_for_three_subjective(api):
    """PRD §3.6: "the per-question value is the arithmetic mean of
    BLIND_A.awarded_points and BLIND_B.awarded_points rounded half up
    to two decimal places — this is the round-per-question-first step,
    and the ordering is pinned ... The per-question values are then
    summed exactly without further rounding to produce
    subjective_points."

    Difficulty design: combinatorial_formula /
    round_per_question_then_sum_for_subjective_total.

    Means: 7.335 → round_half_up → 7.34; 6.665 → 6.67; 5.5 → 5.50.
    Sum 7.34 + 6.67 + 5.50 = 19.51 (vs sum-then-round 19.50).
    """
    # difficulty: combinatorial_formula/round_per_question_then_sum_for_subjective_total
    exam, obj_qs, subj_qs = exam_ready_for_candidates(
        start_time=1000, end_time=10_000,
        num_objective=0, num_subjective=3,
        subjective_max_points=10,
        sampling_rule_spec={"target_count": 3},
    )
    q1, q2, q3 = subj_qs
    reg, attempt, cid = attempt_submitted(
        exam, obj_qs, subj_qs,
        answers={q1["id"]: "ans1", q2["id"]: "ans2", q3["id"]: "ans3"},
    )
    # Score each pair to produce the means above.
    # Q1: 7.34 + 7.33 → mean 7.335 → round 7.34
    resolve_subjective_question(
        exam["id"], attempt["id"], q1["id"],
        blind_a_points=7.34, blind_b_points=7.33,
    )
    # Q2: 6.67 + 6.66 → mean 6.665 → round 6.67 (half up)
    resolve_subjective_question(
        exam["id"], attempt["id"], q2["id"],
        blind_a_points=6.67, blind_b_points=6.66,
    )
    # Q3: 5.50 + 5.50 → mean 5.5 → 5.50
    resolve_subjective_question(
        exam["id"], attempt["id"], q3["id"],
        blind_a_points=5.50, blind_b_points=5.50,
    )
    refreshed = validate_success(
        api.get_attempt(
            exam["id"], attempt["id"], make_candidate_headers(cid),
        ), 200,
    )
    # PRD §3.6: round-per-question-first → 7.34 + 6.67 + 5.50 = 19.51.
    assert refreshed["provisional_score"] == pytest.approx(19.51, abs=0.005)


def test_grading_progress_pct_formula(api, exam_admin_headers):
    """PRD §3.6: "total_slots is the count of GradingAssignment rows
    under non-DISQUALIFIED attempts of this exam; done_slots is the
    subset whose status is RESOLVED or DISCARDED ... When total_slots
    is zero the percentage is reported as 100; otherwise it is 100
    multiplied by done_slots, divided by total_slots, rounded half up
    to two decimal places."

    Setup: one attempt with one subjective question. Right after
    submit, total=2 (BLIND_A + BLIND_B), done=0 → 0.00. After
    resolution, total=2, done=2 → 100.00.
    """
    exam, obj_qs, subj_qs = exam_ready_for_candidates(
        start_time=1000, end_time=10_000,
        num_objective=0, num_subjective=1,
        sampling_rule_spec={"target_count": 1},
    )
    q_subj = subj_qs[0]
    reg, attempt, cid = attempt_submitted(
        exam, obj_qs, subj_qs,
        answers={q_subj["id"]: "ans"},
    )
    # Before resolution.
    pre = validate_success(
        api.get_exam(exam["id"], exam_admin_headers), 200,
    )
    assert pre["grading_progress_pct"] == pytest.approx(0.00, abs=0.01)
    # Resolve the subjective question.
    resolve_subjective_question(
        exam["id"], attempt["id"], q_subj["id"],
        blind_a_points=8.0, blind_b_points=8.0,
    )
    post = validate_success(
        api.get_exam(exam["id"], exam_admin_headers), 200,
    )
    assert post["grading_progress_pct"] == pytest.approx(100.00, abs=0.01)


def test_grading_progress_pct_zero_total_slots_reports_100(api,
                                                           exam_admin_headers):
    """PRD §3.6: "When total_slots is zero the percentage is reported
    as 100."

    An exam with only objective questions has zero
    GradingAssignment rows even after submit.
    """
    exam, obj_qs, _ = exam_ready_for_candidates(
        start_time=1000, end_time=10_000,
        num_objective=1, num_subjective=0,
    )
    reg, attempt, cid = attempt_submitted(exam, obj_qs, [])
    # The exam may already report 100 even before any submit; after a
    # submit with no subjective questions, total_slots == 0.
    res = validate_success(
        api.get_exam(exam["id"], exam_admin_headers), 200,
    )
    assert res["grading_progress_pct"] == pytest.approx(100.00, abs=0.01)


def test_attempt_auto_transitions_submitted_to_graded(api):
    """PRD §3.6: "Once every GradingAssignment row for the attempt is
    in RESOLVED or DISCARDED, the attempt transitions automatically
    SUBMITTED → GRADED."
    """
    exam, obj_qs, subj_qs = exam_ready_for_candidates(
        start_time=1000, end_time=10_000,
        num_objective=0, num_subjective=1,
        sampling_rule_spec={"target_count": 1},
    )
    q_subj = subj_qs[0]
    reg, attempt, cid = attempt_submitted(
        exam, obj_qs, subj_qs, answers={q_subj["id"]: "ans"},
    )
    resolve_subjective_question(
        exam["id"], attempt["id"], q_subj["id"],
        blind_a_points=8.0, blind_b_points=8.0,
    )
    refreshed = validate_success(
        api.get_attempt(
            exam["id"], attempt["id"], make_candidate_headers(cid),
        ), 200,
    )
    assert refreshed["status"] == "GRADED"
