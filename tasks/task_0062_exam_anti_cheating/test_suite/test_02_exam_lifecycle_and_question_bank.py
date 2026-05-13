"""Exam creation, question bank management, open/close registration.

Covers PRD §3.1 question bank rules + DRAFT → OPEN_REGISTRATION feasibility
checks (ERR_QUESTION_BANK_EMPTY, ERR_SAMPLING_INFEASIBLE,
ERR_RUBRIC_INVALID), and the OPEN_REGISTRATION → READY transition.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    add_objective_question,
    add_subjective_question,
    api_client,
    assert_exam,
    assert_question,
    close_registration,
    create_draft_exam,
    create_exam_payload,
    create_objective_question_payload,
    create_subjective_question_payload,
    open_registration,
    validate_error,
    validate_success,
)


# ===========================================================================
# Create exam — happy path
# ===========================================================================
def test_create_exam_starts_in_draft(api, exam_admin_headers):
    """PRD §3.1: "The newly created exam starts with status set to
    DRAFT, max_score and grading_progress_pct both at 0."
    """
    res = api.create_exam(
        create_exam_payload(start_time=1000, end_time=2000),
        exam_admin_headers,
    )
    exam = validate_success(res, 201)
    assert_exam(exam)
    assert exam["status"] == "DRAFT"
    assert exam["max_score"] == 0
    assert exam["grading_progress_pct"] == 0


def test_create_exam_defaults_appeal_window_to_one_day(api, exam_admin_headers):
    """PRD §3.1: "appeal_window_seconds defaults to 86400 (one day)."
    """
    payload = create_exam_payload(start_time=1000, end_time=2000)
    payload.pop("appeal_window_seconds", None)
    res = api.create_exam(payload, exam_admin_headers)
    exam = validate_success(res, 201)
    assert exam["appeal_window_seconds"] == 86400


def test_create_exam_defaults_option_shuffle_true(api, exam_admin_headers):
    """PRD §3.1: "option_shuffle defaults to true."
    """
    payload = create_exam_payload(start_time=1000, end_time=2000)
    payload.pop("option_shuffle", None)
    res = api.create_exam(payload, exam_admin_headers)
    exam = validate_success(res, 201)
    assert exam["option_shuffle"] is True


def test_create_exam_defaults_per_question_time_limit_zero(api, exam_admin_headers):
    """PRD §3.1: "per_question_time_limit_seconds defaults to 0 (no
    per-question cap, only the overall window applies)."
    """
    payload = create_exam_payload(start_time=1000, end_time=2000)
    payload.pop("per_question_time_limit_seconds", None)
    res = api.create_exam(payload, exam_admin_headers)
    exam = validate_success(res, 201)
    assert exam["per_question_time_limit_seconds"] == 0


# ===========================================================================
# Question bank rules — rubric integrity
# ===========================================================================
def test_subjective_rubric_sum_must_equal_max_points(api, exam_admin_headers):
    """PRD §3.1: "Subjective questions additionally require a rubric
    array of { keypoint, points } entries whose points must sum exactly
    to max_points ... A violation of either rubric rule rejects the
    question creation with ERR_RUBRIC_INVALID."
    """
    exam = create_draft_exam()
    # max_points=10, but rubric sums to 9 → violates the rule.
    payload = create_subjective_question_payload(
        max_points=10,
        rubric=[{"keypoint": "kp1", "points": 5},
                {"keypoint": "kp2", "points": 4}],
    )
    res = api.create_question(exam["id"], payload, exam_admin_headers)
    validate_error(res, "ERR_RUBRIC_INVALID")


def test_subjective_rubric_valid_accepted(api, exam_admin_headers):
    """PRD §3.1: rubric points summing to max_points → 201."""
    exam = create_draft_exam()
    payload = create_subjective_question_payload(
        max_points=10,
        rubric=[{"keypoint": "kp1", "points": 6},
                {"keypoint": "kp2", "points": 4}],
    )
    res = api.create_question(exam["id"], payload, exam_admin_headers)
    q = validate_success(res, 201)
    assert_question(q)
    assert q["question_type"] == "SHORT_ANSWER"


def test_objective_question_with_rubric_rejected(api, exam_admin_headers):
    """PRD §3.1: "objective questions must carry no rubric at all. A
    violation of either rubric rule rejects the question creation with
    ERR_RUBRIC_INVALID."
    """
    exam = create_draft_exam()
    payload = create_objective_question_payload(max_points=10)
    payload["rubric"] = [{"keypoint": "kp1", "points": 10}]
    res = api.create_question(exam["id"], payload, exam_admin_headers)
    validate_error(res, "ERR_RUBRIC_INVALID")


# ===========================================================================
# open-registration feasibility (PRD §3.1)
# ===========================================================================
def test_open_registration_with_empty_bank_rejected(api, exam_admin_headers):
    """PRD §3.1: "the bank must contain at least one question (otherwise
    ERR_QUESTION_BANK_EMPTY)."
    """
    exam = create_draft_exam(
        sampling_rule_type="RANDOM",
        sampling_rule_spec={"target_count": 1},
    )
    res = api.open_registration(exam["id"], exam_admin_headers)
    validate_error(res, "ERR_QUESTION_BANK_EMPTY")


def test_open_registration_random_feasible(api, exam_admin_headers):
    """PRD §3.1: "for RANDOM mode the total question count is at least
    the spec's target_count."
    """
    exam = create_draft_exam(
        sampling_rule_type="RANDOM",
        sampling_rule_spec={"target_count": 2},
    )
    add_objective_question(exam["id"], max_points=10)
    add_objective_question(exam["id"], max_points=15)
    res = api.open_registration(exam["id"], exam_admin_headers)
    updated = validate_success(res, 200)
    assert updated["status"] == "OPEN_REGISTRATION"
    # PRD §3.1 side effect: "the exam's max_score is recomputed as the
    # sum of max_points over every question now in the bank."
    assert updated["max_score"] == pytest.approx(25, abs=1e-6)


def test_open_registration_random_infeasible(api, exam_admin_headers):
    """PRD §3.1: feasibility check fails when pool < target_count →
    ERR_SAMPLING_INFEASIBLE.
    """
    exam = create_draft_exam(
        sampling_rule_type="RANDOM",
        sampling_rule_spec={"target_count": 5},
    )
    add_objective_question(exam["id"])  # only 1 question
    res = api.open_registration(exam["id"], exam_admin_headers)
    validate_error(res, "ERR_SAMPLING_INFEASIBLE")


def test_open_registration_stratified_infeasible_when_bucket_short(
    api, exam_admin_headers,
):
    """PRD §3.1: "for STRATIFIED mode every entry in the spec's
    difficulty_buckets map ... is bounded by the number of bank
    questions of that difficulty."
    """
    exam = create_draft_exam(
        sampling_rule_type="STRATIFIED",
        sampling_rule_spec={
            "difficulty_buckets": {"EASY": 2, "MEDIUM": 1, "HARD": 1},
        },
    )
    # Bank: 2 EASY, 1 MEDIUM, 0 HARD → HARD bucket falls short.
    add_objective_question(exam["id"], difficulty="EASY")
    add_objective_question(exam["id"], difficulty="EASY")
    add_objective_question(exam["id"], difficulty="MEDIUM")
    res = api.open_registration(exam["id"], exam_admin_headers)
    validate_error(res, "ERR_SAMPLING_INFEASIBLE")


def test_open_registration_blueprint_infeasible_when_slot_short(
    api, exam_admin_headers,
):
    """PRD §3.1: "for BLUEPRINT mode every ordered slot in the spec's
    slots list ... finds at least count matching questions in the bank."
    """
    exam = create_draft_exam(
        sampling_rule_type="BLUEPRINT",
        sampling_rule_spec={
            "slots": [
                {"topic": "algebra", "question_type": "SINGLE_CHOICE",
                 "difficulty": "EASY", "count": 1},
                {"topic": "geometry", "question_type": "SHORT_ANSWER",
                 "difficulty": "HARD", "count": 1},
            ],
        },
    )
    add_objective_question(exam["id"], topic="algebra", difficulty="EASY")
    # No geometry/SHORT_ANSWER/HARD question.
    res = api.open_registration(exam["id"], exam_admin_headers)
    validate_error(res, "ERR_SAMPLING_INFEASIBLE")


# ===========================================================================
# Lifecycle transitions
# ===========================================================================
def test_close_registration_transitions_to_ready(api, exam_admin_headers):
    """PRD §3.1: "The subsequent close-registration transition
    OPEN_REGISTRATION → READY is unconditional; it merely freezes the
    registration roster."
    """
    exam = create_draft_exam(
        sampling_rule_type="RANDOM",
        sampling_rule_spec={"target_count": 1},
    )
    add_objective_question(exam["id"])
    open_registration(exam["id"])
    res = api.close_registration(exam["id"], exam_admin_headers)
    updated = validate_success(res, 200)
    assert updated["status"] == "READY"


def test_open_registration_on_unknown_exam_returns_not_found(
    api, exam_admin_headers,
):
    """PRD §2.6 / §3.1: existence check precedes business-state check on
    nested resources. Calling open-registration with a bogus exam_id →
    ERR_EXAM_NOT_FOUND."""
    res = api.open_registration(NON_EXISTENT_UUID, exam_admin_headers)
    validate_error(res, "ERR_EXAM_NOT_FOUND")
