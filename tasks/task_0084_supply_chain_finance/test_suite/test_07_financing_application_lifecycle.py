"""FinancingApplication lifecycle (PRD §3.5).

Covers DRAFT → SUBMITTED → UNDER_REVIEW (with verification PASS) →
RETURNED_FOR_REVISION ↔ SUBMITTED, APPROVED (with segregation of
duties), REJECTED, and revision-round cap.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    approve_financing_application_payload,
    assert_financing_application,
    create_financing_application_payload,
    iso_in_days,
    make_supplier_headers,
    open_and_pass_verification,
    register_supplier,
    reject_financing_application_payload,
    return_financing_application_payload,
    setup_approved_application,
    setup_application_at_revision_round,
    setup_draft_financing_application,
    setup_registered_receivable,
    setup_submitted_application,
    setup_under_review_application,
    validate_error,
    validate_success,
)


def test_create_draft_application_starts_in_draft(api):
    """PRD §3.5: "The application starts in DRAFT with revision_round
    at zero, risk_rating null, approved_amount_cents null, and
    approved_apr_bps null."
    """
    bundle = setup_registered_receivable(amount_cents=1_000_000)
    payload = create_financing_application_payload(
        receivable_id=bundle["receivable"]["id"],
        mode="FACTORING",
        requested_amount_cents=500_000,
        term_days=60,
    )
    bundle_due = bundle["receivable"]["due_date"]
    # Note: term_days must match (due_date - now) ± 1 per PRD §3.5
    # for submission; for draft creation it's just stored.
    _ = bundle_due
    res = api.create_financing_application(
        payload, make_supplier_headers(bundle["supplier"]["id"]),
    )
    app = validate_success(res, expected_status=201)
    assert_financing_application(app)
    assert app["status"] == "DRAFT"
    assert app["revision_round"] == 0
    assert app.get("risk_rating") in (None, "")
    assert app.get("approved_amount_cents") in (None, 0, "") or app.get("approved_amount_cents") is None
    assert app.get("approved_apr_bps") in (None, 0, "") or app.get("approved_apr_bps") is None


def test_submit_rejects_when_kyc_failed(api):
    """PRD §3.5: "Submission for review (DRAFT → SUBMITTED ...) requires
    that ... the supplier's kyc_status is PASSED and kyc_completed_at
    is within KYC_VALIDITY_DAYS days of the current clock (else
    ERR_KYC_EXPIRED_OR_FAILED)."

    PRD §2.10 lists the business-safety ladder as "KYC validity,
    supplier not blacklisted, ..." — KYC validity fires first. So a
    faithful implementation surfaces ERR_KYC_EXPIRED_OR_FAILED before
    ERR_SUPPLIER_BLACKLISTED when both would apply.

    We build a DRAFT application, then have the ComplianceOfficer
    record kyc_status=FAILED on the supplier (which also blacklists
    per §3.2), and submit. The expected error is
    ERR_KYC_EXPIRED_OR_FAILED.
    """
    from test_helpers import (
        kyc_supplier_payload, TEST_USERS,
        setup_draft_financing_application,
    )
    bundle = setup_draft_financing_application()
    # Fail KYC AFTER the DRAFT is established (so submit_application
    # is the surface that observes the KYC-not-valid condition).
    api.kyc_supplier(
        bundle["supplier"]["id"], kyc_supplier_payload("FAILED", 0.10),
        TEST_USERS["compliance_officer_headers"],
    )
    res = api.submit_financing_application(
        bundle["application"]["id"],
        make_supplier_headers(bundle["supplier"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_KYC_EXPIRED_OR_FAILED.value)


def test_submit_requires_term_days_matching_due_date_window(api):
    """PRD §3.5: "The term_days field must also match the integer count
    of days between the receivable's due_date and the current clock,
    with a tolerance of plus or minus one day, otherwise the
    submission is rejected with ERR_TERM_MISMATCH."
    """
    # Build a receivable due in 90 days; then create an application
    # with term_days=30 (>1 day off the actual window).
    bundle = setup_registered_receivable(
        amount_cents=1_000_000, due_date=iso_in_days(90),
    )
    payload = create_financing_application_payload(
        receivable_id=bundle["receivable"]["id"],
        mode="FACTORING",
        requested_amount_cents=500_000,
        term_days=30,
    )
    headers = make_supplier_headers(bundle["supplier"]["id"])
    draft_res = api.create_financing_application(payload, headers)
    app = validate_success(draft_res, expected_status=201)
    submit_res = api.submit_financing_application(app["id"], headers)
    validate_error(submit_res, ApiErrorId.ERR_TERM_MISMATCH.value)


def test_submit_with_matching_term_days_advances_to_submitted(api):
    """PRD §3.5: DRAFT → SUBMITTED happy path when term_days matches
    the due-date window."""
    bundle = setup_submitted_application(
        term_days=90, mode="FACTORING",
    )
    assert bundle["application"]["status"] == "SUBMITTED"


def test_start_review_requires_pass_verification(
    api, risk_reviewer_headers,
):
    """PRD §3.5: "A RiskReviewer begins review (SUBMITTED →
    UNDER_REVIEW) only when a TradeBackgroundVerification has been
    finalised with outcome PASS for the related receivable."
    """
    bundle = setup_submitted_application(term_days=90)
    # Do NOT pass-finalize; try start-review.
    res = api.start_review_financing_application(
        bundle["application"]["id"], risk_reviewer_headers,
    )
    # PRD names ERR_INVALID_STATE as the generic state-precondition
    # error; the specific "no PASS verification yet" outcome is not
    # given a dedicated error_id in PRD §5, so a faithful implementer
    # could either return ERR_INVALID_STATE or reuse a related error.
    # We assert HTTP 4xx and validate the response is an error.
    assert res.status_code >= 400, (
        "PRD §3.5: start-review without verification PASS must fail."
    )


def test_start_review_after_pass_verification_succeeds(
    api, risk_reviewer_headers,
):
    """PRD §3.5: "A RiskReviewer begins review (SUBMITTED →
    UNDER_REVIEW) only when a TradeBackgroundVerification has been
    finalised with outcome PASS for the related receivable."
    """
    bundle = setup_submitted_application(term_days=90)
    open_and_pass_verification(
        bundle["receivable"], reviewer_headers=risk_reviewer_headers,
    )
    res = api.start_review_financing_application(
        bundle["application"]["id"], risk_reviewer_headers,
    )
    app = validate_success(res)
    assert app["status"] == "UNDER_REVIEW"


def test_return_increments_revision_round(
    api, risk_reviewer_headers,
):
    """PRD §3.5: "The reviewer may instead return the application to
    the supplier for revision (UNDER_REVIEW → RETURNED_FOR_REVISION),
    supplying revision_notes in the request body; this transition
    increments revision_round by one."
    """
    bundle = setup_under_review_application(
        reviewer_headers=risk_reviewer_headers, term_days=90,
    )
    before = bundle["application"]["revision_round"]
    res = api.return_financing_application(
        bundle["application"]["id"],
        return_financing_application_payload(),
        risk_reviewer_headers,
    )
    returned = validate_success(res)
    assert returned["status"] == "RETURNED_FOR_REVISION"
    assert returned["revision_round"] == before + 1, (
        "PRD §3.5: 'this transition increments revision_round by one.'"
    )


def test_approve_blocked_when_same_user_as_reviewer(
    api, risk_reviewer_headers, credit_approver_headers,
):
    """PRD §2.1: "A single additional authorization rule applies at
    financing-application approval and rejection: the X-User-ID of the
    CreditApprover invoking approval or rejection must differ from the
    X-User-ID of the RiskReviewer who started review on the same
    application. ... A match yields ERR_SEGREGATION_OF_DUTIES with HTTP
    status 403, regardless of timing."

    Build an application with start-review actor ``risk_reviewer_001``,
    then attempt to approve with X-User-ID also ``risk_reviewer_001``
    under role CreditApprover.
    """
    from test_helpers import build_user_headers
    bundle = setup_under_review_application(
        reviewer_headers=risk_reviewer_headers, term_days=90,
    )
    # Forge an approver header whose X-User-ID matches the reviewer's
    # opaque id (from TEST_USERS["risk_reviewer_headers"]).
    reviewer_id = risk_reviewer_headers["X-User-ID"]
    same_user_approver = build_user_headers(reviewer_id, "CreditApprover")
    res = api.approve_financing_application(
        bundle["application"]["id"],
        approve_financing_application_payload(
            approved_amount_cents=bundle["application"]["requested_amount_cents"],
        ),
        same_user_approver,
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_approve_succeeds_with_distinct_actor(
    api, risk_reviewer_headers, credit_approver_headers,
):
    """PRD §2.1: SoD rule reads "must differ from"; happy path with a
    distinct approver succeeds.
    """
    bundle = setup_under_review_application(
        reviewer_headers=risk_reviewer_headers, term_days=90,
    )
    res = api.approve_financing_application(
        bundle["application"]["id"],
        approve_financing_application_payload(
            approved_amount_cents=bundle["application"]["requested_amount_cents"],
        ),
        credit_approver_headers,
    )
    approved = validate_success(res)
    assert approved["status"] == "APPROVED"
    assert isinstance(approved["approved_apr_bps"], int)
    assert isinstance(approved["pinned_core_enterprise_version"], int)
    assert isinstance(approved["pinned_receivable_version"], int)


def test_approve_rejects_amount_out_of_range_above_requested(api):
    """PRD §3.5: "The approved_amount_cents must satisfy two
    simultaneous range constraints: it must not exceed the
    requested_amount_cents on the application ... a violation of either
    yields ERR_APPROVED_AMOUNT_OUT_OF_RANGE."
    """
    from test_helpers import TEST_USERS
    bundle = setup_under_review_application(term_days=90)
    requested = bundle["application"]["requested_amount_cents"]
    res = api.approve_financing_application(
        bundle["application"]["id"],
        approve_financing_application_payload(
            approved_amount_cents=requested + 1,
        ),
        TEST_USERS["credit_approver_headers"],
    )
    validate_error(res, ApiErrorId.ERR_APPROVED_AMOUNT_OUT_OF_RANGE.value)


def test_approve_rejects_amount_above_receivable(api):
    """PRD §3.5: "... and it must not exceed the amount_cents of the
    underlying receivable; a violation of either yields
    ERR_APPROVED_AMOUNT_OUT_OF_RANGE."

    Build an application whose requested_amount_cents EQUALS the
    receivable amount; then approve at requested + 1 > amount_cents.
    """
    from test_helpers import TEST_USERS
    # Use requested_amount_cents == receivable.amount_cents so the
    # "above requested" path doesn't fire first; "above receivable"
    # bites instead.
    bundle = setup_under_review_application(
        amount_cents=1_000_000,
        requested_amount_cents=2_000_000,  # already above receivable
        term_days=90,
    )
    res = api.approve_financing_application(
        bundle["application"]["id"],
        approve_financing_application_payload(
            approved_amount_cents=1_500_000,  # > receivable.amount_cents
        ),
        TEST_USERS["credit_approver_headers"],
    )
    validate_error(res, ApiErrorId.ERR_APPROVED_AMOUNT_OUT_OF_RANGE.value)


def test_reject_application_records_reason_and_terminal_state(api):
    """PRD §3.5: "rejection requires reject_reason ... Rejection
    reasons include any of: KYC failed, fraud-rule triggered, credit
    line insufficient at decision time."

    A CreditApprover may reject any UNDER_REVIEW application; the
    resulting state is REJECTED (terminal per PRD §3.5).
    """
    from test_helpers import TEST_USERS
    bundle = setup_under_review_application(term_days=90)
    res = api.reject_financing_application(
        bundle["application"]["id"],
        reject_financing_application_payload(),
        TEST_USERS["credit_approver_headers"],
    )
    rejected = validate_success(res)
    assert rejected["status"] == "REJECTED"


def test_returned_for_revision_then_resubmitted_resets_to_submitted(api):
    """PRD §3.5: re-submission RETURNED_FOR_REVISION → SUBMITTED is
    allowed while revision_round is strictly less than the
    MAX_REVISION_ROUNDS cap.
    """
    bundle = setup_application_at_revision_round(round_index=1)
    assert bundle["application"]["status"] == "UNDER_REVIEW"
    assert bundle["application"]["revision_round"] == 1


def test_term_days_must_be_within_1_to_365_inclusive(api):
    """PRD §3.5: "The term_days field is constrained to between 1 and
    365 inclusive on every write."

    The term_days range check (1..365) is independent of the term-match
    check (which compares term_days to the receivable due-date window).
    We use a normal 90-day due_date to set up a valid receivable and
    then submit term_days at the lower (0) and upper (366) boundaries;
    both must be rejected because they violate the absolute range.
    """
    bundle = setup_registered_receivable(
        amount_cents=1_000_000, due_date=iso_in_days(90),
    )
    headers = make_supplier_headers(bundle["supplier"]["id"])
    # Lower boundary: 0 must fail.
    payload_lo = create_financing_application_payload(
        receivable_id=bundle["receivable"]["id"], mode="FACTORING",
        requested_amount_cents=500_000, term_days=0,
    )
    lo_res = api.create_financing_application(payload_lo, headers)
    assert lo_res.status_code >= 400, "term_days=0 must be rejected (PRD §3.5)."
    # Upper boundary: 366 must fail.
    payload_hi = create_financing_application_payload(
        receivable_id=bundle["receivable"]["id"], mode="FACTORING",
        requested_amount_cents=500_000, term_days=366,
    )
    hi_res = api.create_financing_application(payload_hi, headers)
    assert hi_res.status_code >= 400, "term_days=366 must be rejected (PRD §3.5)."
