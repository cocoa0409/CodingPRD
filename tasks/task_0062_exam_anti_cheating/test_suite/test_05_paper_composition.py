"""Paper composition: deterministic, per-candidate, archived.

Covers PRD §3.3 for RANDOM / STRATIFIED / BLUEPRINT modes.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    add_objective_question,
    add_subjective_question,
    api_client,
    attempt_active,
    create_draft_exam,
    create_objective_question_payload,
    exam_ready_for_candidates,
    open_registration,
    validate_success,
)


# ===========================================================================
# RANDOM mode
# ===========================================================================
def test_random_sampling_yields_target_count_questions(api):
    """PRD §3.3: "In RANDOM mode the spec carries a target_count ...
    the pool is shuffled with the seeded Fisher–Yates algorithm and the
    first target_count entries are taken."
    """
    exam, obj_qs, _ = exam_ready_for_candidates(
        sampling_rule_type="RANDOM",
        sampling_rule_spec={"target_count": 3},
        num_objective=5,
    )
    reg, attempt, cid = attempt_active(exam)
    assert len(attempt["paper_question_ids"]) == 3
    # Every selected id is from the bank.
    all_q_ids = {q["id"] for q in obj_qs}
    assert set(attempt["paper_question_ids"]).issubset(all_q_ids)


def test_paper_version_hash_is_archived(api):
    """PRD §3.3: "All three of paper_question_ids, paper_option_order,
    and paper_version_hash are immutable from this point onward — they
    form the audit anchor that proves what the candidate actually saw."
    """
    exam, _, _ = exam_ready_for_candidates(num_objective=2)
    reg, attempt, cid = attempt_active(exam)
    assert attempt["paper_version_hash"], (
        "paper_version_hash must be archived on the attempt"
    )
    # SHA-256 hex is 64 chars.
    assert len(attempt["paper_version_hash"]) == 64


# ===========================================================================
# STRATIFIED mode (PRD §3.3)
# ===========================================================================
def test_stratified_mode_picks_per_bucket(api):
    """PRD §3.3: "In STRATIFIED mode the spec carries a
    difficulty_buckets object whose keys are EASY, MEDIUM, and HARD ...
    Each bucket is shuffled independently ... the requested count is
    taken from the front, and the three bucket outputs are concatenated
    in the fixed order EASY first, then MEDIUM, then HARD."

    Difficulty design: combinatorial_formula /
    stratified_sampling_with_three_difficulty_buckets.
    """
    # difficulty: combinatorial_formula/stratified_sampling_with_three_difficulty_buckets
    exam = create_draft_exam(
        sampling_rule_type="STRATIFIED",
        sampling_rule_spec={
            "difficulty_buckets": {"EASY": 2, "MEDIUM": 1, "HARD": 1},
        },
    )
    easy_qs = [
        add_objective_question(exam["id"], difficulty="EASY", max_points=5)
        for _ in range(4)
    ]
    medium_qs = [
        add_objective_question(exam["id"], difficulty="MEDIUM", max_points=5)
        for _ in range(3)
    ]
    hard_qs = [
        add_objective_question(exam["id"], difficulty="HARD", max_points=5)
        for _ in range(2)
    ]
    open_registration(exam["id"])
    reg, attempt, cid = attempt_active(exam)

    # Total count.
    assert len(attempt["paper_question_ids"]) == 4

    # Build a map from question_id → difficulty.
    diffs = {}
    for q in easy_qs + medium_qs + hard_qs:
        diffs[q["id"]] = q["difficulty"]
    chosen = attempt["paper_question_ids"]
    diff_sequence = [diffs[qid] for qid in chosen]
    # Bucket counts.
    assert diff_sequence.count("EASY") == 2
    assert diff_sequence.count("MEDIUM") == 1
    assert diff_sequence.count("HARD") == 1
    # Ordering: EASY first, then MEDIUM, then HARD.
    assert diff_sequence == ["EASY", "EASY", "MEDIUM", "HARD"], (
        f"Bucket ordering violated: {diff_sequence}"
    )


def test_stratified_infeasible_bucket_rejects_open_registration(api,
                                                                exam_admin_headers):
    """PRD §3.3: "if any bucket's eligible size falls short of the
    requested count, composition fails with ERR_SAMPLING_INFEASIBLE."

    The feasibility check is performed at open-registration (PRD §3.1),
    so the error surfaces there.
    """
    from test_helpers import validate_error
    exam = create_draft_exam(
        sampling_rule_type="STRATIFIED",
        sampling_rule_spec={
            "difficulty_buckets": {"EASY": 1, "MEDIUM": 1, "HARD": 2},
        },
    )
    add_objective_question(exam["id"], difficulty="EASY")
    add_objective_question(exam["id"], difficulty="MEDIUM")
    add_objective_question(exam["id"], difficulty="HARD")  # only 1, need 2
    res = api.open_registration(exam["id"], exam_admin_headers)
    validate_error(res, "ERR_SAMPLING_INFEASIBLE")


# ===========================================================================
# BLUEPRINT mode (PRD §3.3)
# ===========================================================================
def test_blueprint_mode_processes_slots_in_declared_order(api):
    """PRD §3.3: "In BLUEPRINT mode the spec carries an ordered slots
    list ... The slots are processed in declared order ... the slot
    outputs are concatenated in the declared slot order."
    """
    exam = create_draft_exam(
        sampling_rule_type="BLUEPRINT",
        sampling_rule_spec={
            "slots": [
                {"topic": "geometry", "question_type": "SINGLE_CHOICE",
                 "difficulty": "HARD", "count": 1},
                {"topic": "algebra", "question_type": "SINGLE_CHOICE",
                 "difficulty": "EASY", "count": 1},
            ],
        },
    )
    geom_q = add_objective_question(
        exam["id"], topic="geometry", difficulty="HARD",
        question_type="SINGLE_CHOICE",
    )
    algebra_q = add_objective_question(
        exam["id"], topic="algebra", difficulty="EASY",
        question_type="SINGLE_CHOICE",
    )
    open_registration(exam["id"])
    reg, attempt, cid = attempt_active(exam)
    assert attempt["paper_question_ids"] == [geom_q["id"], algebra_q["id"]]


# ===========================================================================
# Determinism (PRD §3.3)
# ===========================================================================
def test_paper_composition_is_deterministic_per_attempt(api):
    """PRD §3.3: "The algorithm is deterministic and per-candidate: a
    64-bit unsigned integer seed is derived from the first 16 hex
    characters of the SHA-256 of the attempt's id."

    Claim: re-reading the same attempt returns the same
    paper_question_ids (the values are immutable after composition).
    """
    exam, _, _ = exam_ready_for_candidates(
        num_objective=5,
        sampling_rule_spec={"target_count": 3},
    )
    reg, attempt, cid = attempt_active(exam)
    from test_helpers import make_candidate_headers
    first = attempt["paper_question_ids"]
    refreshed = validate_success(
        api.get_attempt(
            exam["id"], attempt["id"], make_candidate_headers(cid),
        ), 200,
    )
    assert refreshed["paper_question_ids"] == first
    assert refreshed["paper_version_hash"] == attempt["paper_version_hash"]


def test_paper_option_order_present_for_choice_questions(api):
    """PRD §3.3: "The resulting key sequence is recorded against the
    question id in the attempt's paper_option_order map."
    """
    exam, obj_qs, _ = exam_ready_for_candidates(
        num_objective=2,
        sampling_rule_spec={"target_count": 2},
    )
    reg, attempt, cid = attempt_active(exam)
    paper_opts = attempt.get("paper_option_order", {})
    assert isinstance(paper_opts, dict)
    # Every selected SINGLE_CHOICE / MULTI_CHOICE question has its key
    # sequence recorded.
    for qid in attempt["paper_question_ids"]:
        q = next(q for q in obj_qs if q["id"] == qid)
        if q["question_type"] in {"SINGLE_CHOICE", "MULTI_CHOICE"}:
            assert qid in paper_opts, (
                f"paper_option_order must contain selected question {qid}"
            )
            seq = paper_opts[qid]
            assert isinstance(seq, list)
            # Same option keys (just possibly reordered).
            assert set(seq) == {o["option_key"] for o in q["options"]}
