"""Requests that break two rules at once report the earlier rule.

Each scenario below is deliberately doubly invalid, so the response is only
correct if the service evaluates its rules in the pinned precedence order.
"""
from __future__ import annotations

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.fixtures import (
    REVIEW_INSTANT,
    response_window_wave,
    verified_dependent_wave,
)
from test_helpers.test_users import employee_headers

LATE_INSTANT = "2026-10-20T00:00:00Z"

SENSITIVE_SPOUSE_RULE = {
    "SPOUSE": {
        "acceptable_proof_types": ["MARRIAGE_CERTIFICATE", "JOINT_TAX_RETURN"],
        "min_accepted_documents": 2,
    }
}


def _late_submission_response(b, client, *, redaction_applied: bool):
    """Lodge a joint tax return four days past the response deadline."""
    ctx = response_window_wave(
        b, relationships=("SPOUSE",), rule_overrides=SENSITIVE_SPOUSE_RULE
    )
    b.set_clock(LATE_INSTANT)
    payload = f.proof_submission_payload(
        ctx.case["id"],
        ctx.dep["id"],
        "JOINT_TAX_RETURN",
        redaction_applied=redaction_applied,
    )
    response = client.create_proof_submission(
        payload, employee_headers(ctx.employee["id"])
    )
    return ctx, response


def test_the_privacy_redaction_rule_outranks_the_closed_response_window(b, client):
    """An unredacted sensitive document is refused before its timeliness is considered.

    PRD: "18. A sensitive proof type carries `redaction_applied` equal to true —
    `ERR_PRIVACY_REDACTION_REQUIRED` (422), on proof submission."

    Design: Difficulty/priority_pair_validation_conflict/privacy_safety_outranks_response_window_temporal_on_proof_submission
    """
    _ctx, response = _late_submission_response(b, client, redaction_applied=False)

    validate_error(response, E.ERR_PRIVACY_REDACTION_REQUIRED, 422)


def test_the_same_late_document_is_refused_for_timeliness_once_it_is_redacted(b, client):
    """With the privacy rule satisfied the next violation surfaces.

    PRD: "21. The response window is still open — `ERR_RESPONSE_WINDOW_CLOSED`
    (409), on proof submission."

    Design: Difficulty/priority_pair_validation_conflict/privacy_safety_outranks_response_window_temporal_on_proof_submission
    """
    _ctx, response = _late_submission_response(b, client, redaction_applied=True)

    validate_error(response, E.ERR_RESPONSE_WINDOW_CLOSED, 409)


def test_the_refused_submission_leaves_no_row_and_no_case_movement(b, client):
    """A rejected request changes nothing anywhere.

    PRD: "Whenever a workflow in §3 states that an operation propagates to a
    parent, a sibling, or a downstream record, that propagation is part of the
    operation's contract: the whole set commits or the request is rejected and
    nothing changes."

    Design: Difficulty/priority_pair_validation_conflict/privacy_safety_outranks_response_window_temporal_on_proof_submission
    """
    ctx, response = _late_submission_response(b, client, redaction_applied=False)
    validate_error(response, E.ERR_PRIVACY_REDACTION_REQUIRED, 422)

    _rows, meta = b.submissions(dependent_id=ctx.dep["id"])
    assert meta["total_count"] == 0

    case = b.read_case(ctx.case["id"])
    assert case["status"] == "NOTIFIED"
    assert case["proof_submission_count"] == 0
    assert b.read_dependent(ctx.dep["id"])["coverage_status"] == "PENDING_VERIFICATION"


def _submission_against_a_completed_case(b, client):
    """A case that reached COMPLETE, then a birth certificate offered for a spouse."""
    ctx = verified_dependent_wave(b, relationships=("SPOUSE",))
    assert b.read_case(ctx.case["id"])["status"] == "COMPLETE"
    b.set_clock(REVIEW_INSTANT)
    payload = f.proof_submission_payload(
        ctx.case["id"], ctx.dep["id"], "BIRTH_CERTIFICATE"
    )
    response = client.create_proof_submission(
        payload, employee_headers(ctx.employee["id"])
    )
    return ctx, response


def test_case_state_outranks_the_proof_type_rule_on_a_completed_case(b, client):
    """The state screen fires before the acceptability of the offered class is read.

    PRD: "10. Case status admits the operation — `ERR_CASE_STATE_INVALID` (409),
    on proof submission, amnesty removal, appeal filing, and reminders."

    Design: Difficulty/priority_pair_validation_conflict/case_state_outranks_proof_type_referential_on_completed_case
    """
    _ctx, response = _submission_against_a_completed_case(b, client)

    validate_error(response, E.ERR_CASE_STATE_INVALID, 409)


def test_the_completed_case_and_its_verified_dependent_survive_the_refusal(b, client):
    """Nothing about the resolved case or dependent is disturbed.

    PRD: "The dependent's `documentation_complete` becomes true when
    `accepted_proof_type_count` is greater than or equal to the governing rule's
    `min_accepted_documents` — exactly the minimum is sufficient."

    Design: Difficulty/priority_pair_validation_conflict/case_state_outranks_proof_type_referential_on_completed_case
    """
    ctx, response = _submission_against_a_completed_case(b, client)
    validate_error(response, E.ERR_CASE_STATE_INVALID, 409)

    case = b.read_case(ctx.case["id"])
    assert case["status"] == "COMPLETE"
    assert case["proof_submission_count"] == 1

    dependent = b.read_dependent(ctx.dep["id"])
    assert dependent["coverage_status"] == "VERIFIED"
    assert dependent["accepted_proof_type_count"] == 1
