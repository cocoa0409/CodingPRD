"""Submit and forced-submit lifecycle.

Covers PRD §3.5 — candidate submit transition, forced submission at
end_time, end-of-window race semantics, and ERR_EXAM_WINDOW_CLOSED
override on candidate-initiated mutations.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    attempt_active,
    exam_ready_for_candidates,
    list_grading_rows_for_pair,
    make_candidate_headers,
    pre_register_candidates,
    submit_attempt_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def test_submit_active_transitions_to_submitted(api):
    """PRD §3.5: "A candidate-initiated submit transitions the attempt
    ACTIVE → SUBMITTED while the exam remains IN_SESSION ... On success
    the server stamps submitted_at from the current instant ..."
    """
    exam, obj_qs, _ = exam_ready_for_candidates(
        start_time=1000, end_time=2000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    cand_headers = make_candidate_headers(cid)
    advance_clock(1500)
    res = api.submit_attempt(
        exam["id"], attempt["id"],
        submit_attempt_payload(answers={obj_qs[0]["id"]: ["B"]}),
        cand_headers,
    )
    updated = validate_success(res, 200)
    assert updated["status"] == "SUBMITTED"
    assert updated["submitted_at"] == 1500


def test_submit_at_end_minus_one_succeeds_at_end_forced_submit_wins(api):
    """PRD §3.5: forced_submit owns the transition at end_time. At
    end_time - 1, candidate-submit succeeds; at end_time, forced-submit
    pre-empts.

    Difficulty design: boundary_precision_check /
    exam_end_time_boundary_submit_vs_forced_submit.
    """
    # difficulty: boundary_precision_check/exam_end_time_boundary_submit_vs_forced_submit
    exam, obj_qs, _ = exam_ready_for_candidates(
        start_time=1000, end_time=2000, num_objective=1,
    )
    # Two concurrent attempts — pre-register both before any attempt
    # closes registration (PRD §3.1).
    pre_register_candidates(exam, 2)
    reg_a, a3, cid_a = attempt_active(exam)
    reg_b, a4, cid_b = attempt_active(exam)
    cand_a = make_candidate_headers(cid_a)
    cand_b = make_candidate_headers(cid_b)

    # At clock = 1999, A3 submits → 200.
    advance_clock(1999)
    res_a = api.submit_attempt(
        exam["id"], a3["id"],
        submit_attempt_payload(answers={obj_qs[0]["id"]: ["B"]}),
        cand_a,
    )
    updated_a = validate_success(res_a, 200)
    assert updated_a["status"] == "SUBMITTED"
    assert updated_a["submitted_at"] == 1999

    # At clock = 2000, A4's submit is forbidden — forced_submit owns
    # the transition. Per PRD §3.5: candidate-submit "arriving on or
    # after end_time is rejected with ERR_EXAM_WINDOW_CLOSED". After
    # the cascade has executed, A4.status is SUBMITTED with submitter
    # == system; the candidate's call against an already-SUBMITTED row
    # becomes ERR_INVALID_STATE. PRD allows either error.
    advance_clock(2000)
    res_b = api.submit_attempt(
        exam["id"], a4["id"],
        submit_attempt_payload(answers={obj_qs[0]["id"]: ["B"]}),
        cand_b,
    )
    validate_error_is_one_of(
        res_b, ["ERR_EXAM_WINDOW_CLOSED", "ERR_INVALID_STATE"],
    )

    # Verify forced_submit moved A4 → SUBMITTED with submitted_at == end_time.
    a4_after = validate_success(
        api.get_attempt(exam["id"], a4["id"], cand_b), 200,
    )
    assert a4_after["status"] == "SUBMITTED"
    assert a4_after["submitted_at"] == 2000


def test_submit_objective_auto_grades_correct_answers(api):
    """PRD §3.5: "auto-grades every objective question against the
    candidate's responses (single-choice and true-false use scalar
    equality against correct_answer)." PRD §3.6 objective scoring:
    "the server awards the question's max_points when the candidate's
    answer matches correct_answer exactly, and zero otherwise."
    """
    exam, obj_qs, _ = exam_ready_for_candidates(
        start_time=1000, end_time=2000, num_objective=1,
        objective_max_points=15,
    )
    q = obj_qs[0]
    reg, attempt, cid = attempt_active(exam)
    cand_headers = make_candidate_headers(cid)
    # Submit with the correct answer.
    validate_success(
        api.submit_attempt(
            exam["id"], attempt["id"],
            submit_attempt_payload(answers={q["id"]: q["correct_answer"]}),
            cand_headers,
        ), 200,
    )
    refreshed = validate_success(
        api.get_attempt(exam["id"], attempt["id"], cand_headers), 200,
    )
    # No subjective questions → provisional == final == max_points.
    assert refreshed["provisional_score"] == pytest.approx(15, abs=0.01)


def test_submit_objective_wrong_answer_scores_zero(api):
    """PRD §3.6: objective points "zero otherwise" when the answer does
    not match.
    """
    exam, obj_qs, _ = exam_ready_for_candidates(
        start_time=1000, end_time=2000, num_objective=1,
        objective_max_points=10,
    )
    q = obj_qs[0]
    correct = q["correct_answer"]
    wrong = ["A"] if correct != ["A"] else ["C"]
    reg, attempt, cid = attempt_active(exam)
    cand_headers = make_candidate_headers(cid)
    validate_success(
        api.submit_attempt(
            exam["id"], attempt["id"],
            submit_attempt_payload(answers={q["id"]: wrong}),
            cand_headers,
        ), 200,
    )
    refreshed = validate_success(
        api.get_attempt(exam["id"], attempt["id"], cand_headers), 200,
    )
    assert refreshed["provisional_score"] == pytest.approx(0, abs=0.01)


def test_submit_creates_blind_grading_rows_for_subjective(api,
                                                          exam_admin_headers):
    """PRD §3.5: "creates two PENDING GradingAssignment rows for every
    subjective question — one with blind_slot BLIND_A and one with
    blind_slot BLIND_B."
    """
    exam, obj_qs, subj_qs = exam_ready_for_candidates(
        start_time=1000, end_time=2000,
        num_objective=1, num_subjective=1,
        sampling_rule_spec={"target_count": 2},
    )
    q_subj = subj_qs[0]
    reg, attempt, cid = attempt_active(exam)
    cand_headers = make_candidate_headers(cid)
    advance_clock(1500)
    validate_success(
        api.submit_attempt(
            exam["id"], attempt["id"],
            submit_attempt_payload(answers={q_subj["id"]: "freeform text"}),
            cand_headers,
        ), 200,
    )
    rows = list_grading_rows_for_pair(
        exam["id"], attempt["id"], q_subj["id"],
    )
    assert len(rows) == 2
    slots = sorted(r["blind_slot"] for r in rows)
    assert slots == ["BLIND_A", "BLIND_B"]
    for r in rows:
        assert r["status"] == "PENDING"
        assert r.get("marker_id") in (None, "", None)


def test_submit_requires_active_attempt(api):
    """PRD §3.5: candidate-initiated submit transitions ACTIVE →
    SUBMITTED; calling submit when the attempt is not ACTIVE (e.g.,
    already SUBMITTED) → ERR_INVALID_STATE.
    """
    exam, obj_qs, _ = exam_ready_for_candidates(num_objective=1)
    reg, attempt, cid = attempt_active(exam)
    cand_headers = make_candidate_headers(cid)
    validate_success(
        api.submit_attempt(
            exam["id"], attempt["id"],
            submit_attempt_payload(answers={obj_qs[0]["id"]: ["B"]}),
            cand_headers,
        ), 200,
    )
    res = api.submit_attempt(
        exam["id"], attempt["id"],
        submit_attempt_payload(answers={}),
        cand_headers,
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_forced_submit_creates_audit_row(api, exam_admin_headers):
    """PRD §3.5: "an AuditLogEntry row with action_code FORCED_SUBMIT
    is appended for every attempt affected."
    """
    exam, obj_qs, _ = exam_ready_for_candidates(
        start_time=1000, end_time=2000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    advance_clock(2000)  # forces submit
    # Find the audit entry.
    data = validate_success(
        api.list_audit_log(exam_admin_headers, params={"limit": 100}), 200,
    )
    rows = data if isinstance(data, list) else data.get("items", data)
    fs_rows = [
        r for r in rows
        if r.get("action_code") == "FORCED_SUBMIT"
        and r.get("subject_id") == attempt["id"]
    ]
    assert fs_rows, (
        "PRD §3.5 requires a FORCED_SUBMIT AuditLogEntry for every "
        "attempt forced to SUBMITTED at end_time."
    )
