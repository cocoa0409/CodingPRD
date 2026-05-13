"""Subjective grading: claim, score, double-blind invariant,
arbitration cycle.

Covers PRD §3.6 — PENDING → IN_PROGRESS → SUBMITTED → RESOLVED, plus
the arbitration spawn when |BLIND_A - BLIND_B| > 2.0.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    attempt_submitted,
    exam_ready_for_candidates,
    list_grading_rows_for_pair,
    make_marker_headers,
    pre_register_candidates,
    score_grading_payload,
    validate_error,
    validate_success,
)


def _make_submitted_attempt(api, max_pts=10.0):
    """Set up an Exam in IN_SESSION with one objective + one subjective
    question and one SUBMITTED attempt. Returns (exam, q_subj, attempt)."""
    exam, obj_qs, subj_qs = exam_ready_for_candidates(
        start_time=1000, end_time=10_000,
        num_objective=1, num_subjective=1,
        subjective_max_points=max_pts,
        sampling_rule_spec={"target_count": 2},
    )
    reg, attempt, cid = attempt_submitted(exam, obj_qs, subj_qs)
    return exam, subj_qs[0], attempt


# ===========================================================================
# Claim
# ===========================================================================
def test_marker_claims_blind_a(api, marker_headers):
    """PRD §3.6: "The claim transition PENDING → IN_PROGRESS requires
    that the acting marker has not previously claimed the sibling
    blind_slot for the same (attempt_id, question_id) pair."
    """
    exam, q_subj, attempt = _make_submitted_attempt(api)
    rows = list_grading_rows_for_pair(exam["id"], attempt["id"], q_subj["id"])
    blind_a = next(r for r in rows if r["blind_slot"] == "BLIND_A")
    res = api.claim_grading_assignment(
        exam["id"], blind_a["id"], marker_headers,
    )
    claimed = validate_success(res, 200)
    assert claimed["status"] == "IN_PROGRESS"


def test_marker_cannot_claim_both_blind_slots_double_blind(api):
    """PRD §3.6: "A violation rejects the claim with
    ERR_DOUBLE_BLIND_VIOLATION."
    """
    exam, q_subj, attempt = _make_submitted_attempt(api)
    rows = list_grading_rows_for_pair(exam["id"], attempt["id"], q_subj["id"])
    blind_a = next(r for r in rows if r["blind_slot"] == "BLIND_A")
    blind_b = next(r for r in rows if r["blind_slot"] == "BLIND_B")
    same_marker = make_marker_headers("marker-double-blind")
    # First claim succeeds.
    validate_success(
        api.claim_grading_assignment(exam["id"], blind_a["id"], same_marker),
        200,
    )
    # Same marker tries the sibling slot → rejected.
    res = api.claim_grading_assignment(
        exam["id"], blind_b["id"], same_marker,
    )
    validate_error(res, "ERR_DOUBLE_BLIND_VIOLATION")


def test_marker_can_claim_same_blind_slot_across_different_attempts(api):
    """PRD §3.6: the double-blind rule is scoped to a single
    (attempt_id, question_id) pair. The same marker may freely claim
    BLIND_A on attempt-A question-Q AND BLIND_A on attempt-B question-Q.

    Difficulty design: resource_temporal_overlap /
    marker_at_most_one_active_grading_per_attempt_question_pair.
    """
    # difficulty: resource_temporal_overlap/marker_at_most_one_active_grading_per_attempt_question_pair
    exam, obj_qs, subj_qs = exam_ready_for_candidates(
        start_time=1000, end_time=10_000,
        num_objective=1, num_subjective=1,
        sampling_rule_spec={"target_count": 2},
    )
    q_subj = subj_qs[0]
    pre_register_candidates(exam, 2)
    reg1, a1, cid1 = attempt_submitted(exam, obj_qs, subj_qs)
    reg2, a2, cid2 = attempt_submitted(exam, obj_qs, subj_qs)
    rows1 = list_grading_rows_for_pair(exam["id"], a1["id"], q_subj["id"])
    rows2 = list_grading_rows_for_pair(exam["id"], a2["id"], q_subj["id"])
    a1_blind_a = next(r for r in rows1 if r["blind_slot"] == "BLIND_A")
    a1_blind_b = next(r for r in rows1 if r["blind_slot"] == "BLIND_B")
    a2_blind_a = next(r for r in rows2 if r["blind_slot"] == "BLIND_A")
    same_marker = make_marker_headers("marker-cross-attempt")
    # Claim BLIND_A on attempt 1.
    validate_success(
        api.claim_grading_assignment(exam["id"], a1_blind_a["id"], same_marker),
        200,
    )
    # Claim BLIND_A on attempt 2 — different (attempt_id, question_id) pair,
    # so allowed.
    validate_success(
        api.claim_grading_assignment(exam["id"], a2_blind_a["id"], same_marker),
        200,
    )
    # Sanity: still cannot claim BLIND_B on attempt 1.
    res = api.claim_grading_assignment(
        exam["id"], a1_blind_b["id"], same_marker,
    )
    validate_error(res, "ERR_DOUBLE_BLIND_VIOLATION")


# ===========================================================================
# Score
# ===========================================================================
def test_score_with_awarded_out_of_range_rejected(api, marker_headers):
    """PRD §3.6: "awarded_points must lie between 0 and the question's
    max_points inclusive (otherwise ERR_AWARDED_OUT_OF_RANGE)."
    """
    exam, q_subj, attempt = _make_submitted_attempt(api, max_pts=10.0)
    rows = list_grading_rows_for_pair(exam["id"], attempt["id"], q_subj["id"])
    blind_a = next(r for r in rows if r["blind_slot"] == "BLIND_A")
    validate_success(
        api.claim_grading_assignment(exam["id"], blind_a["id"], marker_headers),
        200,
    )
    res = api.score_grading_assignment(
        exam["id"], blind_a["id"],
        score_grading_payload(11.0),  # max_points=10
        marker_headers,
    )
    validate_error(res, "ERR_AWARDED_OUT_OF_RANGE")


def test_score_with_rubric_sum_mismatch_rejected(api, marker_headers):
    """PRD §3.6: "the sum of points in rubric_breakdown must equal
    awarded_points exactly (otherwise ERR_RUBRIC_SUM_MISMATCH)."
    """
    exam, q_subj, attempt = _make_submitted_attempt(api, max_pts=10.0)
    rows = list_grading_rows_for_pair(exam["id"], attempt["id"], q_subj["id"])
    blind_a = next(r for r in rows if r["blind_slot"] == "BLIND_A")
    validate_success(
        api.claim_grading_assignment(exam["id"], blind_a["id"], marker_headers),
        200,
    )
    res = api.score_grading_assignment(
        exam["id"], blind_a["id"],
        score_grading_payload(
            8.0,
            rubric_breakdown=[
                {"keypoint": "kp1", "points": 5},
                {"keypoint": "kp2", "points": 4},  # sum=9, not 8
            ],
        ),
        marker_headers,
    )
    validate_error(res, "ERR_RUBRIC_SUM_MISMATCH")


def test_blind_pair_within_threshold_both_resolved(api):
    """PRD §3.6: "if the gap is at most 2.0, the two rows transition
    together to RESOLVED and the attempt's provisional_score is
    recomputed."
    """
    exam, q_subj, attempt = _make_submitted_attempt(api, max_pts=10.0)
    rows = list_grading_rows_for_pair(exam["id"], attempt["id"], q_subj["id"])
    blind_a = next(r for r in rows if r["blind_slot"] == "BLIND_A")
    blind_b = next(r for r in rows if r["blind_slot"] == "BLIND_B")
    m1 = make_marker_headers("m1-within")
    m2 = make_marker_headers("m2-within")
    validate_success(
        api.claim_grading_assignment(exam["id"], blind_a["id"], m1), 200,
    )
    validate_success(
        api.score_grading_assignment(
            exam["id"], blind_a["id"],
            score_grading_payload(8.0),
            m1,
        ), 200,
    )
    validate_success(
        api.claim_grading_assignment(exam["id"], blind_b["id"], m2), 200,
    )
    validate_success(
        api.score_grading_assignment(
            exam["id"], blind_b["id"],
            score_grading_payload(7.0),  # |delta|=1 ≤ 2.0
            m2,
        ), 200,
    )
    # Both rows should be RESOLVED now.
    rows_after = list_grading_rows_for_pair(
        exam["id"], attempt["id"], q_subj["id"],
    )
    statuses = sorted(r["status"] for r in rows_after)
    assert statuses == ["RESOLVED", "RESOLVED"], (
        f"Expected both RESOLVED, got {statuses}"
    )


def test_blind_pair_above_threshold_spawns_arbitration(api):
    """PRD §3.6: "if the gap strictly exceeds 2.0, a third
    GradingAssignment row is spawned with blind_slot ARBITRATION,
    status PENDING."

    Difficulty design: non_linear_state_machine /
    grading_assignment_arbitration_cycle.
    """
    # difficulty: non_linear_state_machine/grading_assignment_arbitration_cycle
    exam, q_subj, attempt = _make_submitted_attempt(api, max_pts=10.0)
    rows = list_grading_rows_for_pair(exam["id"], attempt["id"], q_subj["id"])
    blind_a = next(r for r in rows if r["blind_slot"] == "BLIND_A")
    blind_b = next(r for r in rows if r["blind_slot"] == "BLIND_B")
    m1 = make_marker_headers("m1-arb")
    m2 = make_marker_headers("m2-arb")
    validate_success(
        api.claim_grading_assignment(exam["id"], blind_a["id"], m1), 200,
    )
    validate_success(
        api.score_grading_assignment(
            exam["id"], blind_a["id"], score_grading_payload(10.0), m1,
        ), 200,
    )
    validate_success(
        api.claim_grading_assignment(exam["id"], blind_b["id"], m2), 200,
    )
    validate_success(
        api.score_grading_assignment(
            exam["id"], blind_b["id"], score_grading_payload(4.0),
            m2,
        ), 200,
    )
    # |10 - 4| = 6 > 2.0 → ARBITRATION row spawned, blind rows remain
    # SUBMITTED.
    rows_after = list_grading_rows_for_pair(
        exam["id"], attempt["id"], q_subj["id"],
    )
    slots = sorted(r["blind_slot"] for r in rows_after)
    assert slots == ["ARBITRATION", "BLIND_A", "BLIND_B"]
    arb = next(r for r in rows_after if r["blind_slot"] == "ARBITRATION")
    assert arb["status"] == "PENDING"
    for r in rows_after:
        if r["blind_slot"] in ("BLIND_A", "BLIND_B"):
            assert r["status"] == "SUBMITTED", (
                "PRD §3.6: blind rows remain SUBMITTED pending arbitration; "
                f"got {r['status']}"
            )


def test_arbitration_resolution_pulls_all_three(api):
    """PRD §3.6: "Once the arbitrator claims and scores that third row,
    all three rows transition to RESOLVED together."
    """
    exam, q_subj, attempt = _make_submitted_attempt(api, max_pts=10.0)
    rows = list_grading_rows_for_pair(exam["id"], attempt["id"], q_subj["id"])
    blind_a = next(r for r in rows if r["blind_slot"] == "BLIND_A")
    blind_b = next(r for r in rows if r["blind_slot"] == "BLIND_B")
    m1 = make_marker_headers("m1-pull")
    m2 = make_marker_headers("m2-pull")
    m3 = make_marker_headers("m3-pull")
    validate_success(
        api.claim_grading_assignment(exam["id"], blind_a["id"], m1), 200,
    )
    validate_success(
        api.score_grading_assignment(
            exam["id"], blind_a["id"], score_grading_payload(10.0), m1,
        ), 200,
    )
    validate_success(
        api.claim_grading_assignment(exam["id"], blind_b["id"], m2), 200,
    )
    validate_success(
        api.score_grading_assignment(
            exam["id"], blind_b["id"], score_grading_payload(4.0), m2,
        ), 200,
    )
    # Arbitration row.
    after = list_grading_rows_for_pair(exam["id"], attempt["id"], q_subj["id"])
    arb = next(r for r in after if r["blind_slot"] == "ARBITRATION")
    validate_success(
        api.claim_grading_assignment(exam["id"], arb["id"], m3), 200,
    )
    validate_success(
        api.score_grading_assignment(
            exam["id"], arb["id"], score_grading_payload(6.0), m3,
        ), 200,
    )
    # All three RESOLVED.
    final = list_grading_rows_for_pair(exam["id"], attempt["id"], q_subj["id"])
    statuses = sorted(r["status"] for r in final)
    assert statuses == ["RESOLVED", "RESOLVED", "RESOLVED"]


def test_arbitration_value_supersedes_blind_pair_in_score(api):
    """PRD §3.6: "the per-question value is the arbitrator's
    awarded_points rounded half up to two decimal places, and the two
    blind awards no longer contribute."

    Sets up arbitrator=6.0 → provisional_score for the subjective
    question = 6.00 (objective contribution = 0 because the candidate's
    submit answers a single objective with a deliberately-wrong key).
    """
    exam, obj_qs, subj_qs = exam_ready_for_candidates(
        start_time=1000, end_time=10_000,
        num_objective=1, num_subjective=1,
        objective_max_points=20,
        subjective_max_points=10,
        sampling_rule_spec={"target_count": 2},
    )
    # Deliberately wrong objective answer so objective_points = 0.
    obj_q = obj_qs[0]
    wrong_answer = ["A"] if obj_q["correct_answer"] != ["A"] else ["C"]
    reg, attempt, cid = attempt_submitted(
        exam, obj_qs, subj_qs,
        answers={obj_q["id"]: wrong_answer,
                 subj_qs[0]["id"]: "free-form"},
    )
    q_subj = subj_qs[0]
    rows = list_grading_rows_for_pair(exam["id"], attempt["id"], q_subj["id"])
    blind_a = next(r for r in rows if r["blind_slot"] == "BLIND_A")
    blind_b = next(r for r in rows if r["blind_slot"] == "BLIND_B")
    m1 = make_marker_headers("m1-supersede")
    m2 = make_marker_headers("m2-supersede")
    m3 = make_marker_headers("m3-supersede")
    validate_success(
        api.claim_grading_assignment(exam["id"], blind_a["id"], m1), 200,
    )
    validate_success(
        api.score_grading_assignment(
            exam["id"], blind_a["id"], score_grading_payload(10.0), m1,
        ), 200,
    )
    validate_success(
        api.claim_grading_assignment(exam["id"], blind_b["id"], m2), 200,
    )
    validate_success(
        api.score_grading_assignment(
            exam["id"], blind_b["id"], score_grading_payload(4.0), m2,
        ), 200,
    )
    after = list_grading_rows_for_pair(exam["id"], attempt["id"], q_subj["id"])
    arb = next(r for r in after if r["blind_slot"] == "ARBITRATION")
    validate_success(
        api.claim_grading_assignment(exam["id"], arb["id"], m3), 200,
    )
    validate_success(
        api.score_grading_assignment(
            exam["id"], arb["id"], score_grading_payload(6.0), m3,
        ), 200,
    )
    from test_helpers import make_candidate_headers
    refreshed = validate_success(
        api.get_attempt(
            exam["id"], attempt["id"], make_candidate_headers(cid),
        ), 200,
    )
    # Objective: 0 (wrong); Subjective: 6.00 from arbitration.
    assert refreshed["provisional_score"] == pytest.approx(6.00, abs=0.01)


def test_grading_already_claimed_returns_error(api):
    """PRD §3.6: "Two markers concurrently attempting the same row
    resolve by first-writer-wins: exactly one claim succeeds and is
    recorded with marker_id set to the winner's X-User-ID; the loser
    receives ERR_GRADING_ALREADY_CLAIMED."

    Sequential analogue: marker_2 tries to claim a row already
    IN_PROGRESS — must surface ERR_GRADING_ALREADY_CLAIMED (or
    ERR_INVALID_STATE because the row left PENDING).
    """
    from test_helpers import validate_error_is_one_of
    exam, q_subj, attempt = _make_submitted_attempt(api)
    rows = list_grading_rows_for_pair(exam["id"], attempt["id"], q_subj["id"])
    blind_a = next(r for r in rows if r["blind_slot"] == "BLIND_A")
    m1 = make_marker_headers("first-claim")
    m2 = make_marker_headers("second-claim")
    validate_success(
        api.claim_grading_assignment(exam["id"], blind_a["id"], m1), 200,
    )
    res = api.claim_grading_assignment(exam["id"], blind_a["id"], m2)
    validate_error_is_one_of(
        res, ["ERR_GRADING_ALREADY_CLAIMED", "ERR_INVALID_STATE"],
    )
