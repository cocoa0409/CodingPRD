"""Publish-scores → SCORES_PUBLISHED → APPEAL_WINDOW → ARCHIVED.

Covers PRD §3.7 lifecycle gates and the appeal-window-close cascade.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    attempt_submitted,
    exam_ready_for_candidates,
    make_candidate_headers,
    resolve_subjective_question,
    setup_finalized_exam_for_appeal,
    submit_appeal_for,
    validate_error,
    validate_success,
)


def test_publish_scores_requires_progress_100(api, exam_admin_headers):
    """PRD §3.7: "The transition GRADING → SCORES_PUBLISHED is gated on
    grading_progress_pct reaching exactly 100; calling it earlier
    rejects with ERR_GRADING_INCOMPLETE."
    """
    exam, obj_qs, subj_qs = exam_ready_for_candidates(
        start_time=1000, end_time=2000,
        num_objective=0, num_subjective=1,
        sampling_rule_spec={"target_count": 1},
    )
    q_subj = subj_qs[0]
    reg, attempt, cid = attempt_submitted(
        exam, obj_qs, subj_qs, answers={q_subj["id"]: "ans"},
    )
    # Force exam → GRADING; subjective rows are still PENDING.
    advance_clock(2000)
    res = api.publish_scores(exam["id"], exam_admin_headers)
    validate_error(res, "ERR_GRADING_INCOMPLETE")


def test_publish_scores_succeeds_when_progress_100(api, exam_admin_headers):
    """PRD §3.7: "On success, every non-DISQUALIFIED attempt has its
    final_score frozen and is moved to FINALIZED."
    """
    exam, obj_qs, subj_qs = exam_ready_for_candidates(
        start_time=1000, end_time=2000,
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
    advance_clock(2000)
    res = api.publish_scores(exam["id"], exam_admin_headers)
    updated = validate_success(res, 200)
    assert updated["status"] == "SCORES_PUBLISHED"
    refreshed_attempt = validate_success(
        api.get_attempt(
            exam["id"], attempt["id"], make_candidate_headers(cid),
        ), 200,
    )
    assert refreshed_attempt["status"] == "FINALIZED"


def test_scores_published_then_appeal_window(api, exam_admin_headers):
    """PRD §3.7: "One server-clock tick later the exam transitions
    automatically SCORES_PUBLISHED → APPEAL_WINDOW."
    """
    exam, obj_qs, subj_qs = exam_ready_for_candidates(
        start_time=1000, end_time=2000,
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
    advance_clock(2000)
    validate_success(api.publish_scores(exam["id"], exam_admin_headers), 200)
    # One tick later → APPEAL_WINDOW.
    advance_clock(2001)
    refreshed = validate_success(
        api.get_exam(exam["id"], exam_admin_headers), 200,
    )
    assert refreshed["status"] == "APPEAL_WINDOW"


def test_appeal_window_close_rejects_pending_appeals(api, exam_admin_headers,
                                                    appeal_officer_headers):
    """PRD §3.7: "and remains there until the clock reaches publication
    time plus appeal_window_seconds, at which point the automatic
    transition APPEAL_WINDOW → ARCHIVED fires. At that moment every
    Appeal row still in SUBMITTED, UNDER_REVIEW, or DECISION_PENDING is
    forcibly transitioned to REJECTED with no score adjustment."

    Difficulty design: cross_entity_state_dependency /
    appeal_claim_requires_exam_in_appeal_window.
    """
    # difficulty: cross_entity_state_dependency/appeal_claim_requires_exam_in_appeal_window
    scenario = setup_finalized_exam_for_appeal(
        appeal_window_seconds=100,  # Short window
        start_time=1000, end_time=2000,
    )
    exam = scenario["exam"]
    attempt = scenario["attempt"]
    subj_q = scenario["subjective_question"]
    cid = scenario["candidate_id"]
    # Verify exam is in APPEAL_WINDOW.
    assert exam["status"] == "APPEAL_WINDOW"
    # Submit an appeal.
    appeal = submit_appeal_for(
        exam["id"], attempt["id"], subj_q["id"], cid,
    )
    assert appeal["status"] == "SUBMITTED"
    # Advance the clock well past appeal_window_close.
    # The publish happened at end_time=2000; APPEAL_WINDOW began at
    # 2001. Window length = 100s → close at 2101.
    advance_clock(2_500)
    exam_after = validate_success(
        api.get_exam(exam["id"], exam_admin_headers), 200,
    )
    assert exam_after["status"] == "ARCHIVED"
    # The pending appeal must be REJECTED by the cascade.
    appeals = validate_success(
        api.list_appeals(exam["id"], exam_admin_headers), 200,
    )
    rows = appeals if isinstance(appeals, list) else appeals.get(
        "items", appeals,
    )
    target = next((a for a in rows if a["id"] == appeal["id"]), None)
    assert target is not None
    assert target["status"] == "REJECTED"


def test_claim_appeal_after_window_close_rejected(api, appeal_officer_headers,
                                                  exam_admin_headers):
    """PRD §3.7: claim must occur while the exam remains in
    APPEAL_WINDOW (otherwise ERR_EXAM_NOT_IN_APPEAL_WINDOW)."""
    scenario = setup_finalized_exam_for_appeal(
        appeal_window_seconds=100, start_time=1000, end_time=2000,
    )
    exam = scenario["exam"]
    attempt = scenario["attempt"]
    subj_q = scenario["subjective_question"]
    cid = scenario["candidate_id"]
    appeal = submit_appeal_for(
        exam["id"], attempt["id"], subj_q["id"], cid,
    )
    advance_clock(2_500)  # past appeal window
    res = api.claim_appeal(
        exam["id"], appeal["id"], appeal_officer_headers,
    )
    # Either the appeal is REJECTED (state) or the exam-state check
    # surfaces ERR_EXAM_NOT_IN_APPEAL_WINDOW.
    from test_helpers import validate_error_is_one_of
    validate_error_is_one_of(
        res, ["ERR_EXAM_NOT_IN_APPEAL_WINDOW", "ERR_INVALID_STATE"],
    )
