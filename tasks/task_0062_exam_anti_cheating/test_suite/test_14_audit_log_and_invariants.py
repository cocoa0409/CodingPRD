"""Audit log discipline and append-only invariants.

Covers PRD §2.4 append-only (no updated_at / version) and §2.9
audit log discipline.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    assert_audit_entry,
    attempt_active,
    attempt_submitted,
    exam_ready_for_candidates,
    make_candidate_headers,
    post_abnormal_event,
    setup_finalized_exam_for_appeal,
    submit_appeal_for,
    drive_appeal_to_decision,
    validate_success,
)


def test_abnormal_event_is_append_only(api, proctor_headers):
    """PRD §2.4: "IdentityVerificationRecord, AbnormalEvent, and
    AuditLogEntry ... carry only id and created_at." AbnormalEvent must
    not surface updated_at / version.
    """
    exam, _, _ = exam_ready_for_candidates(
        start_time=1000, end_time=10_000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    event = post_abnormal_event(
        exam["id"], attempt["id"],
        detected_at=1100,
        behavior_rule_code="WINDOW_SWITCH",
        monitoring_channel="SCREEN",
        marking_mode="REALTIME_ALERT",
        headers=proctor_headers,
    )
    assert "updated_at" not in event, (
        "PRD §2.4: AbnormalEvent is append-only — updated_at must be "
        "omitted."
    )
    assert "version" not in event, (
        "PRD §2.4: AbnormalEvent is append-only — version must be omitted."
    )


def test_identity_record_is_append_only(api):
    """PRD §2.4: IdentityVerificationRecord must carry only id +
    created_at (no updated_at / version)."""
    exam, _, _ = exam_ready_for_candidates(num_objective=1)
    # PRD §3.1 forbids registration past OPEN_REGISTRATION; pre-register
    # both candidates before the first attempt_active closes the window.
    from test_helpers import pre_register_candidates
    pre_register_candidates(exam, 2)
    reg, attempt, cid = attempt_active(exam)
    # attempt_active issues exactly one PRE_EXAM record. Inspect it via
    # round-tripping a fresh PRE_EXAM call on a separate attempt.
    from test_helpers import (
        attempt_enrolled_only, identity_verification_payload,
    )
    reg2, attempt2, cid2 = attempt_enrolled_only(exam)
    cand2 = make_candidate_headers(cid2)
    validate_success(
        api.begin_identity_check(exam["id"], attempt2["id"], cand2), 200,
    )
    res = api.submit_identity_verification(
        exam["id"], attempt2["id"],
        identity_verification_payload(verification_phase="PRE_EXAM"),
        cand2,
    )
    record = validate_success(res, 201)
    assert "updated_at" not in record
    assert "version" not in record


def test_forced_submit_audit_entry_shape(api, exam_admin_headers):
    """PRD §2.9: Each AuditLogEntry records subject_type, subject_id,
    actor_role, actor_id, action_code, and delta. PRD §3.5: forced
    submit appends an entry with action_code FORCED_SUBMIT.
    """
    exam, obj_qs, _ = exam_ready_for_candidates(
        start_time=1000, end_time=2000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    advance_clock(2000)
    data = validate_success(
        api.list_audit_log(exam_admin_headers, params={"limit": 100}), 200,
    )
    rows = data if isinstance(data, list) else data.get("items", data)
    fs_rows = [
        r for r in rows
        if r.get("action_code") == "FORCED_SUBMIT"
        and r.get("subject_id") == attempt["id"]
    ]
    assert fs_rows
    entry = fs_rows[0]
    assert_audit_entry(entry)
    # subject_type for an EXAM_ATTEMPT forced submit.
    assert entry["subject_type"] == "EXAM_ATTEMPT"


def test_appeal_approved_audit_entry_with_delta(api, exam_admin_headers,
                                                 appeal_officer_headers):
    """PRD §3.7: "an AuditLogEntry row is appended with action_code
    APPEAL_APPROVED and the before/after final score recorded in
    delta."

    Difficulty design: compensating_invariant /
    appeal_score_adjustment_audit_total_invariant (partial — single
    APPROVED appeal verifies the audit row shape).
    """
    scenario = setup_finalized_exam_for_appeal(
        blind_a_points=8.0, blind_b_points=7.0,
        objective_max_points=20, subjective_max_points=10,
        objective_correct=True,
    )
    exam = scenario["exam"]
    attempt = scenario["attempt"]
    subj_q = scenario["subjective_question"]
    cid = scenario["candidate_id"]
    appeal = submit_appeal_for(
        exam["id"], attempt["id"], subj_q["id"], cid,
    )
    drive_appeal_to_decision(
        exam["id"], appeal["id"],
        secondary_awarded_points=9.0,
        decision="APPROVED",
        officer_headers=appeal_officer_headers,
    )
    data = validate_success(
        api.list_audit_log(exam_admin_headers, params={"limit": 100}), 200,
    )
    rows = data if isinstance(data, list) else data.get("items", data)
    # Look for either APPEAL_APPROVED or SCORE_ADJUSTED on the attempt.
    matches = [
        r for r in rows
        if r.get("subject_id") == attempt["id"]
        and r.get("action_code") in {"APPEAL_APPROVED", "SCORE_ADJUSTED"}
    ]
    assert matches, (
        "PRD §3.7 requires an audit row for the appeal's APPROVED "
        "decision with before/after final_score in delta."
    )
    score_adj = next(
        (r for r in matches if r.get("action_code") == "SCORE_ADJUSTED"),
        matches[0],
    )
    delta = score_adj.get("delta") or {}
    # Delta carries before/after final_score.
    assert "before" in delta and "after" in delta, (
        f"PRD §2.9 + §3.7: audit row delta must carry before/after pair; "
        f"got {delta!r}"
    )
    # before = 27.50, after = 29.00.
    before = float(delta["before"]) if not isinstance(
        delta["before"], dict,
    ) else float(delta["before"].get("final_score", delta["before"]))
    after = float(delta["after"]) if not isinstance(
        delta["after"], dict,
    ) else float(delta["after"].get("final_score", delta["after"]))
    assert before == pytest.approx(27.50, abs=0.01)
    assert after == pytest.approx(29.00, abs=0.01)


def test_audit_log_append_only_field_shape(api, exam_admin_headers,
                                           proctor_headers):
    """PRD §2.4 + §2.9: AuditLogEntry rows carry only id + created_at.
    """
    exam, _, _ = exam_ready_for_candidates(
        start_time=1000, end_time=2000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    advance_clock(2000)  # FORCED_SUBMIT row created
    data = validate_success(
        api.list_audit_log(exam_admin_headers, params={"limit": 100}), 200,
    )
    rows = data if isinstance(data, list) else data.get("items", data)
    assert rows
    for row in rows:
        assert "updated_at" not in row
        assert "version" not in row


def test_identity_verification_count_invariant_across_dq_cascade(
    api, proctor_headers,
):
    """PRD §3.2: "identity_verification_count is required to equal at
    every observation the number of IdentityVerificationRecord rows ...
    This invariant must hold after every PRE_EXAM creation, after every
    IN_EXAM_RECHECK creation, and after every disqualification cascade
    — the cascade does not delete records, so the count is preserved
    across it."

    Difficulty design: compensating_invariant /
    identity_verification_count_append_only_invariant.
    """
    # difficulty: compensating_invariant/identity_verification_count_append_only_invariant
    exam, _, _ = exam_ready_for_candidates(
        start_time=1000, end_time=10_000, num_objective=1,
    )
    reg, attempt, cid = attempt_active(exam)
    cand_headers = make_candidate_headers(cid)
    # Before cascade: count == 1.
    pre = validate_success(
        api.get_attempt(exam["id"], attempt["id"], cand_headers), 200,
    )
    assert pre["identity_verification_count"] == 1

    # Trigger the disqualification cascade (CRITICAL MULTI_PERSON).
    post_abnormal_event(
        exam["id"], attempt["id"],
        detected_at=1100,
        behavior_rule_code="MULTI_PERSON",
        monitoring_channel="SCREEN",
        marking_mode="REALTIME_ALERT",
        headers=proctor_headers,
    )
    # After cascade: status DISQUALIFIED, BUT identity_verification_count
    # is preserved (no decrement, no deletion).
    post = validate_success(
        api.get_attempt(exam["id"], attempt["id"], cand_headers), 200,
    )
    assert post["status"] == "DISQUALIFIED"
    assert post["identity_verification_count"] == 1, (
        "PRD §3.2: cascade must NOT decrement identity_verification_count."
    )
