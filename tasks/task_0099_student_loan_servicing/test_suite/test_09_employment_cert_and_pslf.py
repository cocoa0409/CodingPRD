"""Employment certification lifecycle and PSLF qualifying-payment count.

Anchors: PRD §3.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    advance_clock_by_days,
    api_client,
    approve_employment_certification,
    assert_employment_certification,
    create_borrower_with_loan_in_repayment,
    create_employment_certification_payload,
    record_borrower_payment,
    reset_clock_to,
    submit_employment_certification,
    submit_and_approve_employment_certification,
    update_employment_certification_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_and_activate_plan,
    setup_pslf_borrower_with_n_qualifying_payments,
)


# ---------------------------------------------------------------------------
# 1. Submission and approval (PRD §3.8)
# ---------------------------------------------------------------------------
def test_submit_employment_certification_initial_state(api):
    """PRD §3.8: "The borrower submits an EmploymentCertification
    carrying employer_name, employer_type ... and a window of
    period_start and period_end".

    Claim: a valid POST yields status=SUBMITTED.
    """
    borrower, _, _ = create_borrower_with_loan_in_repayment()
    cert = submit_employment_certification(
        borrower["id"], use_borrower_role=True,
    )
    assert_employment_certification(cert)
    assert cert["status"] == "SUBMITTED"


def test_submit_with_end_not_after_start_rejected(api):
    """PRD §3.8: "the certification is rejected at submission with
    ERR_BAD_DATE_WINDOW if period_start is not strictly less than
    period_end."

    Claim: period_start >= period_end → ERR_BAD_DATE_WINDOW.
    """
    borrower, _, _ = create_borrower_with_loan_in_repayment()
    res = api.create_employment_certification(
        borrower["id"],
        create_employment_certification_payload(
            period_start="2025-01-01T00:00:00.000Z",
            period_end="2025-01-01T00:00:00.000Z",
        ),
        TEST_USERS["servicer_admin_headers"],
    )
    validate_error(res, "ERR_BAD_DATE_WINDOW")


def test_approve_certification_records_reviewed_by(api):
    """PRD §3.8: "approval requires employer_type to be one of the
    three qualifying values (GOVERNMENT, NONPROFIT_501C3, or
    OTHER_NONPROFIT_QUALIFYING) ... The certifier's X-User-ID is
    stamped into reviewed_by."

    Claim: APPROVED certification carries reviewed_by equal to the
    certifier's X-User-ID.
    """
    borrower, _, _ = create_borrower_with_loan_in_repayment()
    cert = submit_and_approve_employment_certification(borrower["id"])
    assert cert["status"] == "APPROVED"
    assert cert["reviewed_by"] == "certifier-001", (
        "PRD §3.8: reviewed_by must equal the certifier's X-User-ID"
    )


def test_approve_private_non_qualifying_rejected(api):
    """PRD §3.8: "a PRIVATE_NON_QUALIFYING certification cannot be
    approved."

    Claim: PATCH /status=APPROVED on a PRIVATE_NON_QUALIFYING cert
    is rejected.
    """
    borrower, _, _ = create_borrower_with_loan_in_repayment()
    cert = submit_employment_certification(
        borrower["id"], employer_type="PRIVATE_NON_QUALIFYING",
    )
    res = api.update_employment_certification(
        borrower["id"], cert["id"],
        update_employment_certification_payload(status="APPROVED"),
        TEST_USERS["servicer_certifier_headers"],
    )
    # PRD says PRIVATE_NON_QUALIFYING "cannot be approved" but does
    # not pin a specific error_id; the state-machine rejection is the
    # uniquely-derivable outcome. validate_error_is_one_of would be
    # appropriate; here we just check failure.
    assert res.status_code >= 400, (
        "PRD §3.8: PRIVATE_NON_QUALIFYING approval must fail"
    )


def test_reject_certification_records_reason(api):
    """PRD §3.8: "Rejection records a free-text rejection_reason."

    Claim: PATCH status=REJECTED with rejection_reason yields
    status=REJECTED + rejection_reason set.
    """
    borrower, _, _ = create_borrower_with_loan_in_repayment()
    cert = submit_employment_certification(borrower["id"])
    res = api.update_employment_certification(
        borrower["id"], cert["id"],
        {"status": "REJECTED", "rejection_reason": "documentation incomplete"},
        TEST_USERS["servicer_certifier_headers"],
    )
    rejected = validate_success(res, 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "documentation incomplete"


# ---------------------------------------------------------------------------
# 2. PSLF qualifying-payment counting (PRD §3.8)
# ---------------------------------------------------------------------------
def test_payment_in_approved_cert_window_counts_as_pslf(api):
    """PRD §3.8: "Five conditions must all hold: (1) the loan's
    loan_type is one of DIRECT_SUBSIDIZED, DIRECT_UNSUBSIDIZED, or
    DIRECT_PLUS; (2) the payment's received_at falls within an
    APPROVED EmploymentCertification's window for this borrower,
    inclusive on both endpoints ... (3) at the time of received_at
    the borrower had an ACTIVE RepaymentPlan of type STANDARD_10,
    IBR, PAYE, or SAVE covering the loan; (4) the sum of that
    allocation's principal_cents and interest_cents is at least the
    per-loan scheduled-monthly share ... (5) the loan's status at
    the moment of received_at was not DEFAULT and not DELINQUENT.
    Each qualifying (payment, loan) increments the loan's
    qualifying_pslf_payment_count by 1."

    Claim: a single full-installment BORROWER payment under an
    APPROVED GOVERNMENT cert with an ACTIVE STANDARD_10 plan
    increments qualifying_pslf_payment_count by exactly 1.
    """
    borrower, loan, plan, cert, _ = (
        setup_pslf_borrower_with_n_qualifying_payments(n_qualifying=1)
    )
    fetched = validate_success(
        api.get_loan(borrower["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    assert fetched["qualifying_pslf_payment_count"] == 1, (
        f"PRD §3.8: one full-installment payment in approved window "
        f"with ACTIVE STANDARD_10 plan must yield count==1, got "
        f"{fetched['qualifying_pslf_payment_count']}"
    )


def test_payment_outside_cert_window_does_not_count(api):
    """PRD §3.8: "(2) the payment's received_at falls within an
    APPROVED EmploymentCertification's window for this borrower,
    inclusive on both endpoints — period_start is at or before
    received_at and received_at is at or before period_end".

    Claim: a payment whose received_at falls BEFORE the certification
    window does NOT increment qualifying_pslf_payment_count.
    """
    reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
    borrower, loan, current = create_borrower_with_loan_in_repayment(
        original_principal_cents=1_000_000, interest_rate_bps=500,
    )
    plan = create_and_activate_plan(
        borrower["id"], "STANDARD_10", [loan["id"]],
    )
    # Make a payment NOW (before any cert exists).
    installment = plan["monthly_payment_cents"]
    pay_clock = advance_clock_by_days(30, from_stamp=current)
    record_borrower_payment(
        borrower["id"], installment, received_at=pay_clock,
        source="BORROWER",
    )
    # Now submit an EmploymentCertification whose window starts AFTER
    # the payment.
    later_clock = advance_clock_by_days(60, from_stamp=pay_clock)
    cert = submit_employment_certification(
        borrower["id"],
        period_start=later_clock, period_end="2030-12-31T23:59:59.999Z",
        employer_type="GOVERNMENT",
    )
    approve_employment_certification(borrower["id"], cert["id"])
    fetched = validate_success(
        api.get_loan(borrower["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    assert fetched["qualifying_pslf_payment_count"] == 0, (
        "PRD §3.8: payment received BEFORE the cert window must not "
        f"count; got {fetched['qualifying_pslf_payment_count']}"
    )


def test_employment_cert_approval_retroactively_counts(api):
    """PRD §3.8: "Approving an EmploymentCertification retroactively
    re-runs the PSLF qualification recount across the borrower's
    entire payment history."

    Claim: payments made BEFORE certification approval are counted
    when the cert window covers them and is then approved.
    """
    reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
    borrower, loan, current = create_borrower_with_loan_in_repayment(
        original_principal_cents=1_000_000, interest_rate_bps=500,
    )
    plan = create_and_activate_plan(
        borrower["id"], "STANDARD_10", [loan["id"]],
    )
    installment = plan["monthly_payment_cents"]
    # Submit (but do not approve) an EmploymentCertification covering
    # a wide window.
    cert = submit_employment_certification(
        borrower["id"],
        period_start=current,
        period_end="2030-12-31T23:59:59.999Z",
        employer_type="GOVERNMENT",
    )
    # Make a payment under the (still-SUBMITTED) cert window.
    pay_clock = advance_clock_by_days(30, from_stamp=current)
    record_borrower_payment(
        borrower["id"], installment, received_at=pay_clock,
        source="BORROWER",
    )
    # Before approval: count should be 0 (cert is not APPROVED).
    before = validate_success(
        api.get_loan(borrower["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    assert before["qualifying_pslf_payment_count"] == 0
    # Approve cert — retroactive recount should bump count to 1.
    approve_employment_certification(borrower["id"], cert["id"])
    after = validate_success(
        api.get_loan(borrower["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    assert after["qualifying_pslf_payment_count"] == 1, (
        "PRD §3.8: APPROVED cert must retroactively count prior "
        "payments in its window"
    )


def test_payment_pslf_qualifying_flag_set_on_payment(api):
    """PRD §3.4: "After allocation, the system performs the live
    PSLF qualification check (described in §3.8) and stamps
    pslf_qualifying on the new payment to record whether it counts
    as a qualifying payment for any covered loan."

    Claim: a qualifying payment carries pslf_qualifying == true on
    the Payment record.
    """
    borrower, loan, plan, cert, _ = (
        setup_pslf_borrower_with_n_qualifying_payments(n_qualifying=1)
    )
    # Read the latest payment via the paginated list endpoint.
    from test_helpers import validate_paginated
    payments, _ = validate_paginated(
        api.list_payments(borrower["id"],
                          TEST_USERS["servicer_admin_headers"]),
    )
    assert payments, "expected one payment from setup"
    assert any(p["pslf_qualifying"] is True for p in payments), (
        "PRD §3.4: a qualifying payment must have pslf_qualifying=true"
    )
