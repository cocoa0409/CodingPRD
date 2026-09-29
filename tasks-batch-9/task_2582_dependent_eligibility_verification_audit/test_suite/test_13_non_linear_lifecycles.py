"""The two lifecycles that are not forward-only pipelines.

An audit case can be walked backwards out of escalation by a granted appeal, and
a proof submission carries two status dimensions that advance independently of
one another on the same row.
"""
from __future__ import annotations

from test_helpers.assertions import assert_instant_equals
from test_helpers.fixtures import (
    REVIEW_INSTANT,
    appeal_wave,
    response_window_wave,
)

APPEAL_FILED_INSTANT = "2026-10-20T00:00:00Z"

TWO_DEPENDENTS = ("SPOUSE", "CHILD_BIOLOGICAL")


def _escalated_case_with_an_appeal_under_review(b):
    """Two silent dependents escalated, then an appeal taken on the first of them."""
    return appeal_wave(
        b,
        stage="ESCALATION",
        relationships=TWO_DEPENDENTS,
        grounds="ADMINISTRATIVE_ERROR",
        appeal_at=APPEAL_FILED_INSTANT,
    )


def test_granting_an_appeal_walks_the_escalated_case_back_to_in_progress(b):
    """A sibling dependent is still unresolved, so the case re-opens rather than completing.

    PRD: "Fifth, the case itself re-opens: it moves `ESCALATED → IN_PROGRESS`
    when at least one member of its `in_scope_dependent_ids` is still in
    `PENDING_VERIFICATION` or `TERMINATION_PENDING`, and instead moves
    `ESCALATED → COMPLETE` with `completed_at` set when the restored dependent
    was the last unresolved one."

    Design: Difficulty/non_linear_state_machine/audit_case_cycles_escalated_back_to_in_progress_on_appeal_grant
    """
    ctx = _escalated_case_with_an_appeal_under_review(b)
    assert b.read_case(ctx.case["id"])["status"] == "ESCALATED"

    granted = b.decide_appeal(ctx.appeal["id"], "GRANT")

    assert granted["status"] == "GRANTED"
    assert_instant_equals(granted["decided_at"], APPEAL_FILED_INSTANT)

    case = b.read_case(ctx.case["id"])
    assert case["status"] == "IN_PROGRESS"
    assert case["unverified_dependent_count"] == 1
    assert case["completed_at"] is None
    assert b.read_dependent(ctx.dep2["id"])["coverage_status"] == "TERMINATION_PENDING"

    program = b.read_program(ctx.program["id"])
    assert program["non_responsive_case_count"] == 0
    assert program["termination_pending_count"] == 1


def test_granting_an_appeal_restores_the_dependent_and_rescinds_its_notice(b):
    """The exception is granted in lieu of documentation and the notice is unwound.

    PRD: "When the dependent is in `TERMINATION_PENDING` and its
    `TerminationNotice` is still in `ISSUED`, the dependent moves
    `TERMINATION_PENDING → VERIFIED` with `documentation_complete` set to true —
    the exception is granted in lieu of documentation."

    Design: Difficulty/non_linear_state_machine/audit_case_cycles_escalated_back_to_in_progress_on_appeal_grant
    """
    ctx = _escalated_case_with_an_appeal_under_review(b)
    notice = b.notice_for(ctx.dep["id"])
    assert notice["status"] == "ISSUED"

    b.decide_appeal(ctx.appeal["id"], "GRANT")

    dependent = b.read_dependent(ctx.dep["id"])
    assert dependent["coverage_status"] == "VERIFIED"
    assert dependent["documentation_complete"] is True

    rescinded = b.read_notice(notice["id"])
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["rescission_reason"] == "APPEAL_GRANTED"
    assert_instant_equals(rescinded["rescinded_at"], APPEAL_FILED_INSTANT)

    program = b.read_program(ctx.program["id"])
    assert program["verified_dependent_count"] == 1


# Two distinct accepted classes are required, so a single acceptance cannot fire
# the completeness cascade and hide the privacy dimension's movement.
TWO_DOCUMENT_SPOUSE_RULE = {
    "SPOUSE": {
        "acceptable_proof_types": ["MARRIAGE_CERTIFICATE", "JOINT_TAX_RETURN"],
        "min_accepted_documents": 2,
    }
}


def _sensitive_submission_under_review(b):
    """A redacted joint tax return lodged inside the response window."""
    ctx = response_window_wave(
        b, relationships=("SPOUSE",), rule_overrides=TWO_DOCUMENT_SPOUSE_RULE
    )
    b.set_clock(REVIEW_INSTANT)
    ctx.submission = b.submit_proof(
        ctx.case["id"],
        ctx.dep["id"],
        ctx.employee["id"],
        "JOINT_TAX_RETURN",
        redaction_applied=True,
    )
    return ctx


def test_a_redaction_request_parks_the_review_dimension_and_advances_privacy(b):
    """One decision moves review only to UNDER_REVIEW while privacy goes on hold.

    PRD: "A **redaction request** leaves the review dimension parked at
    `UNDER_REVIEW` — moving it `SUBMITTED → UNDER_REVIEW` — while advancing the
    privacy dimension to `REDACTION_REQUIRED`; this is the clearest illustration
    of the two dimensions moving independently, and `reviewed_by_user_id` is
    stamped here too."

    Design: Difficulty/non_linear_state_machine/proof_submission_privacy_dimension_moves_independently_of_review_dimension
    """
    ctx = _sensitive_submission_under_review(b)
    assert ctx.submission["review_status"] == "SUBMITTED"
    assert ctx.submission["privacy_class"] == "SENSITIVE"
    assert ctx.submission["privacy_status"] == "REDACTED"

    parked = b.request_redaction(ctx.submission["id"])

    assert parked["review_status"] == "UNDER_REVIEW"
    assert parked["privacy_status"] == "REDACTION_REQUIRED"
    assert parked["reviewed_by_user_id"] == "u_analyst_1"


def test_the_redaction_upload_cures_privacy_and_leaves_review_exactly_as_it_was(b):
    """The upload discharges the privacy obligation and nothing else.

    PRD: "Crucially, `review_status` is left exactly as it was: the upload cures
    the privacy obligation and nothing else, and the analyst must still come back
    and decide the document on its merits."

    Design: Difficulty/non_linear_state_machine/proof_submission_privacy_dimension_moves_independently_of_review_dimension
    """
    ctx = _sensitive_submission_under_review(b)
    b.request_redaction(ctx.submission["id"])

    cured = b.upload_redaction(
        ctx.submission["id"],
        employee_id=ctx.employee["id"],
        redacted_document_reference="s3://redacted/1040-2025-masked.pdf",
    )

    assert cured["privacy_status"] == "REDACTED"
    assert cured["review_status"] == "UNDER_REVIEW"
    assert cured["redacted_document_reference"] == "s3://redacted/1040-2025-masked.pdf"


def test_accepting_the_cured_submission_moves_only_the_review_dimension(b):
    """Acceptance advances review to ACCEPTED and leaves privacy at REDACTED.

    PRD: "An **accept** moves the review dimension `SUBMITTED → ACCEPTED`, or
    `UNDER_REVIEW → ACCEPTED` for a submission that had been parked, and it is
    permitted only when the submission's `privacy_status` is `NOT_REQUIRED` or
    `REDACTED`; a submission still sitting at `REDACTION_REQUIRED`, or one already
    `PURGED`, cannot be accepted and the attempt is refused with
    `ERR_PRIVACY_HOLD`."

    Design: Difficulty/non_linear_state_machine/proof_submission_privacy_dimension_moves_independently_of_review_dimension
    """
    ctx = _sensitive_submission_under_review(b)
    b.request_redaction(ctx.submission["id"])
    b.upload_redaction(ctx.submission["id"], employee_id=ctx.employee["id"])

    accepted = b.accept_proof(ctx.submission["id"])

    assert accepted["review_status"] == "ACCEPTED"
    assert accepted["privacy_status"] == "REDACTED"

    dependent = b.read_dependent(ctx.dep["id"])
    assert dependent["accepted_proof_type_count"] == 1
    assert dependent["documentation_complete"] is False
    assert dependent["coverage_status"] == "PENDING_VERIFICATION"
    assert b.read_case(ctx.case["id"])["status"] == "IN_PROGRESS"
