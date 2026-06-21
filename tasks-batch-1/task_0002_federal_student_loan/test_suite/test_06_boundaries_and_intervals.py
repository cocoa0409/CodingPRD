"""Boundary-precision and interval-semantics tests.

Covers the 270-day delinquency threshold (exactly at and just under), and the
PSLF qualifying-employment closed-interval semantics (payment on period_end
included).
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    set_clock, create_borrower, create_loan, walk_loan_to_repayment,
    setup_loan_with_active_standard_plan,
    create_and_certify_qualifying_employment,
    post_payment,
    TEST_USERS, ApiErrorId,
)


LS = TEST_USERS["loan_servicer_headers"]
CA = TEST_USERS["collections_agent_headers"]


def test_default_threshold_exactly_270_days_passes(api):
    """Loan with delinquency_days == 270 (exactly at threshold) → default
    declaration succeeds.

    PRD §3.8: "A CollectionsAgent may declare default by transitioning a loan
    from REPAYMENT to DEFAULT; the transition requires delinquency_days to be
    at least 270, and an attempt to declare default with a lower count is
    rejected with ERR_DEFAULT_THRESHOLD_NOT_MET."

    Design: Difficulty/boundary_precision_check/boundary_default_threshold_exactly_270_passes
    """
    set_clock("2025-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Bd B", ssn_last4="0050")
    loan = create_loan(
        borrower["id"], loan_type="DIRECT_UNSUB",
        principal_cents=100_000, interest_rate_bps=500,
        disbursement_date="2025-06-01T00:00:00Z",
    )
    walk_loan_to_repayment(loan["id"])
    # 2025-06-01 + 270 days = 2026-02-26 (exactly).
    set_clock("2026-02-26T00:00:00Z")
    res = api.declare_default(loan["id"], CA)
    loan_after = validate_success(res, 200)
    assert loan_after["status"] == "DEFAULT"


def test_default_threshold_269_days_rejected(api):
    """Loan with delinquency_days == 269 (just under threshold) → default
    declaration rejected with ERR_DEFAULT_THRESHOLD_NOT_MET.

    PRD §3.8: "A CollectionsAgent may declare default by transitioning a loan
    from REPAYMENT to DEFAULT; the transition requires delinquency_days to be
    at least 270, and an attempt to declare default with a lower count is
    rejected with ERR_DEFAULT_THRESHOLD_NOT_MET."

    Design: Corner/validations/default_threshold_below_270_rejected
    """
    set_clock("2025-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Thr B", ssn_last4="0025")
    loan = create_loan(
        borrower["id"], loan_type="DIRECT_UNSUB",
        principal_cents=100_000, interest_rate_bps=500,
        disbursement_date="2025-06-01T00:00:00Z",
    )
    walk_loan_to_repayment(loan["id"])
    set_clock("2026-02-25T00:00:00Z")  # 269 days
    res = api.declare_default(loan["id"], CA)
    validate_error(res, ApiErrorId.ERR_DEFAULT_THRESHOLD_NOT_MET.value)


def test_pslf_qualifying_employment_payment_on_period_end_counts(api):
    """A payment whose payment_date EQUALS period_end is included — the PRD
    declares the qualifying-employment window is a closed interval at both ends.

    PRD §3.7: "Fourth, there must exist a QualifyingEmployment belonging to the
    loan's borrower whose status is CERTIFIED, whose employer_type is either
    GOVERNMENT or NONPROFIT_501C3, and whose employment window (the closed
    interval from period_start to period_end, inclusive at both ends) contains
    p's payment_date."

    Design: Difficulty/boundary_precision_check/boundary_pslf_qualifying_employer_interval_closed_at_period_end
    """
    # Walk loan to REPAYMENT BEFORE period_end so the payment dated on
    # period_end can satisfy PRD §3.7 predicate 5.
    borrower, loan, _plan = setup_loan_with_active_standard_plan(
        clock_iso="2026-01-01T00:00:00Z",
        full_name="Bd P", ssn_last4="0051",
        loan_type="DIRECT_UNSUB", principal_cents=3_000_000,
        interest_rate_bps=533,
        disbursement_date="2025-01-01T00:00:00Z",
        plan_effective_date="2026-01-01T00:00:00Z",
    )
    create_and_certify_qualifying_employment(
        borrower["id"],
        employer_name="City Hall", employer_type="GOVERNMENT",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-06-30T00:00:00Z",
    )
    set_clock("2026-07-15T00:00:00Z")
    # Payment date EXACTLY equals period_end.
    pay = post_payment(
        loan["id"], borrower["id"],
        amount_cents=100_000, payment_date="2026-06-30T00:00:00Z",
    )
    applied = validate_success(api.apply_payment(pay["id"], LS), 200)
    assert applied["status"] == "APPLIED"
    assert applied["is_pslf_qualifying"] is True, (
        "Payment dated exactly on period_end must be PSLF-qualifying "
        "(closed interval at both ends)."
    )


def test_pslf_qualifying_employment_payment_on_period_end_inclusive_redundant_check(api):
    """Second independent assertion of the same closed-interval rule — uses a
    distinct borrower and verifies is_pslf_qualifying directly via the apply
    response.

    PRD §3.7: "Fourth, there must exist a QualifyingEmployment belonging to the
    loan's borrower whose status is CERTIFIED, whose employer_type is either
    GOVERNMENT or NONPROFIT_501C3, and whose employment window (the closed
    interval from period_start to period_end, inclusive at both ends) contains
    p's payment_date."

    Design: Difficulty/resource_temporal_overlap/qualifying_employment_closed_interval_inclusive_end
    """
    # Walk loan to REPAYMENT BEFORE period_end so the payment dated on
    # period_end can satisfy PRD §3.7 predicate 5.
    borrower, loan, _plan = setup_loan_with_active_standard_plan(
        clock_iso="2026-01-01T00:00:00Z",
        full_name="Itv1", ssn_last4="0070",
        loan_type="DIRECT_UNSUB", principal_cents=3_000_000,
        interest_rate_bps=533,
        disbursement_date="2025-01-01T00:00:00Z",
        plan_effective_date="2026-01-01T00:00:00Z",
    )
    create_and_certify_qualifying_employment(
        borrower["id"],
        employer_name="Dept of X", employer_type="GOVERNMENT",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-06-30T00:00:00Z",
    )
    set_clock("2026-07-15T00:00:00Z")
    pay = post_payment(
        loan["id"], borrower["id"],
        amount_cents=100_000, payment_date="2026-06-30T00:00:00Z",
    )
    applied = validate_success(api.apply_payment(pay["id"], LS), 200)
    assert applied["is_pslf_qualifying"] is True
