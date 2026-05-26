"""Interest-accrual semantics tests.

Covers the chronological per-day rounding (4560 cents over 30 days at
1_111_111 principal, 5% rate), divergence from the sum-then-round variant
(which would yield 4566), and DIRECT_SUB IN_SCHOOL zero-subsidy accrual.
"""
from test_helpers import (
    api_client, validate_success,
    set_clock, create_borrower, create_loan, walk_loan_to_repayment,
    setup_borrower_and_loan_in_school,
    TEST_USERS,
)


LS = TEST_USERS["loan_servicer_headers"]


def test_interest_accrual_chronological_30_days_yields_4560(api):
    """30-day half-open window with principal=1_111_111 and rate=500 bps yields
    accrued_interest_cents = 4560 (rounding each day to integer cents before
    summing).

    PRD §3.3: "On any other day the day's accrual is the current
    principal_balance_cents multiplied by the daily rate, rounded half-up to
    integer cents before being added to accrued_interest_cents."
    PRD §3.3: "the engine does not sum fractional accruals across the window
    and then round at the end — the latter would produce different integer-cent
    results for the same inputs and is not the chosen interpretation."

    Design: Difficulty/dual_variant_calc/interest_accrual_chronological_vs_sum_then_round_diverge
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Acc B", ssn_last4="0001")
    loan = create_loan(
        borrower["id"], loan_type="DIRECT_UNSUB",
        principal_cents=1_111_111, interest_rate_bps=500,
        disbursement_date="2026-06-01T00:00:00Z",
    )
    loan = walk_loan_to_repayment(loan["id"])
    # Advance clock by 30 days
    set_clock("2026-07-01T00:00:00Z")
    res = api.get_loan(loan["id"], LS)
    loan_after = validate_success(res, 200)
    assert loan_after["accrued_interest_cents"] == 4560, (
        f"Expected accrued_interest_cents=4560 (chronological per-day rounding), "
        f"got {loan_after['accrued_interest_cents']}"
    )


def test_interest_accrual_not_equal_sum_then_round(api):
    """Same 30-day scenario must NOT yield 4566 — that would be the
    sum-then-round variant which PRD explicitly rejects.

    PRD §3.3: "the engine does not sum fractional accruals across the window
    and then round at the end — the latter would produce different integer-cent
    results for the same inputs and is not the chosen interpretation."

    Design: Difficulty/combinatorial_formula/interest_accrual_mode_b_round_per_day_then_sum_pinned
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Rnd B", ssn_last4="0002")
    loan = create_loan(
        borrower["id"], loan_type="DIRECT_UNSUB",
        principal_cents=1_111_111, interest_rate_bps=500,
        disbursement_date="2026-06-01T00:00:00Z",
    )
    loan = walk_loan_to_repayment(loan["id"])
    set_clock("2026-07-01T00:00:00Z")
    res = api.get_loan(loan["id"], LS)
    loan_after = validate_success(res, 200)
    assert loan_after["accrued_interest_cents"] == 4560
    assert loan_after["accrued_interest_cents"] != 4566, (
        "accrued_interest_cents must not equal 4566 — that result indicates the "
        "rejected sum-then-round interpretation."
    )


def test_direct_sub_in_school_accrues_zero_interest(api):
    """DIRECT_SUB Loan in IN_SCHOOL after a 30-day clock advance has
    accrued_interest_cents = 0 (subsidized).

    PRD §3.2: "While the loan is in IN_SCHOOL, GRACE, or DEFERMENT, a
    DIRECT_SUB loan accrues no interest at all; the same loan in FORBEARANCE
    does accrue."

    Design: Corner/state_machines/direct_sub_in_school_accrues_zero_interest_subsidy
    """
    borrower, loan = setup_borrower_and_loan_in_school(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Sub B", ssn_last4="0009",
        loan_type="DIRECT_SUB", principal_cents=1_111_111,
        interest_rate_bps=500,
    )
    set_clock("2026-07-01T00:00:00Z")
    res = api.get_loan(loan["id"], LS)
    loan_after = validate_success(res, 200)
    assert loan_after["accrued_interest_cents"] == 0, (
        f"DIRECT_SUB in IN_SCHOOL expected accrued_interest_cents=0 "
        f"(subsidized), got {loan_after['accrued_interest_cents']}"
    )
