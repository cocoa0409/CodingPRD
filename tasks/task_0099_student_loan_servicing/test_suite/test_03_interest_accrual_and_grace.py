"""Daily interest accrual, simulation clock, GRACE → REPAYMENT exit
including the capitalization rules per loan type.

Anchors: PRD §2.6, §3.2, §3.3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    advance_clock_by_days,
    api_client,
    assert_loan,
    create_borrower,
    create_loan,
    create_loan_in_grace,
    create_loan_in_repayment,
    reset_clock_to,
    round_half_up_to_int,
    separate_loan,
    validate_success,
)
from test_helpers.fixtures import create_borrower_with_loan_in_repayment


def _expected_accrued(principal: int, bps: int, days: int) -> int:
    """PRD §3.3 simple-daily formula, rounded half-up per loan per call."""
    daily_rate = bps / 10_000.0 / 365.0
    return round_half_up_to_int(principal * daily_rate * days)


# ---------------------------------------------------------------------------
# 1. GRACE accrual rules per loan type (PRD §3.2)
# ---------------------------------------------------------------------------
def test_grace_period_subsidized_does_not_accrue(api):
    """PRD §3.2: "Interest accrual during GRACE depends on the loan
    type: a DIRECT_SUBSIDIZED loan accrues no interest during grace
    because it sits in the federal subsidy window."

    Claim: subsidized loan in GRACE has accrued_interest_cents == 0
    after 180 days.
    """
    reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
    b = create_borrower()
    loan = create_loan(b["id"], loan_type="DIRECT_SUBSIDIZED",
                       original_principal_cents=1_000_000,
                       interest_rate_bps=500)
    separate_loan(b["id"], loan["id"])
    advance_clock_by_days(60, from_stamp=TEST_DEFAULTS["INITIAL_CLOCK"])
    fetched = validate_success(
        api.get_loan(b["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    assert fetched["status"] == "GRACE"
    assert fetched["accrued_interest_cents"] == 0, (
        "PRD §3.2: subsidized loan must accrue no interest during GRACE"
    )


@pytest.mark.parametrize("loan_type", ["DIRECT_UNSUBSIDIZED", "DIRECT_PLUS"])
def test_grace_period_unsubsidized_and_plus_accrue(api, loan_type):
    """PRD §3.2: "both DIRECT_UNSUBSIDIZED and DIRECT_PLUS continue
    to accrue interest day by day."

    Claim: unsubsidized/PLUS accrue daily during GRACE.
    """
    reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
    b = create_borrower()
    loan = create_loan(b["id"], loan_type=loan_type,
                       original_principal_cents=1_000_000,
                       interest_rate_bps=500)
    separate_loan(b["id"], loan["id"])
    advance_clock_by_days(30, from_stamp=TEST_DEFAULTS["INITIAL_CLOCK"])
    fetched = validate_success(
        api.get_loan(b["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    expected = _expected_accrued(1_000_000, 500, 30)
    assert fetched["accrued_interest_cents"] == expected, (
        f"PRD §3.3 simple-daily accrual: 1,000,000 * 0.05/365 * 30 "
        f"round_half_up = {expected}, got {fetched['accrued_interest_cents']}"
    )


# ---------------------------------------------------------------------------
# 2. GRACE -> REPAYMENT auto-transition at 180 days (PRD §3.2)
# ---------------------------------------------------------------------------
def test_grace_to_repayment_at_180_days(api):
    """PRD §3.2: "When the simulation clock crosses the boundary of
    180 days past status_entered_at for a loan in GRACE, the system
    automatically transitions the loan from GRACE to REPAYMENT."

    Claim: clock crossing 180 days transitions GRACE → REPAYMENT.
    """
    reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
    b = create_borrower()
    loan = create_loan(b["id"])
    separate_loan(b["id"], loan["id"])
    advance_clock_by_days(181, from_stamp=TEST_DEFAULTS["INITIAL_CLOCK"])
    fetched = validate_success(
        api.get_loan(b["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    assert fetched["status"] == "REPAYMENT", (
        "PRD §3.2: GRACE → REPAYMENT must fire when clock crosses 180 days"
    )


@pytest.mark.parametrize("loan_type", ["DIRECT_UNSUBSIDIZED", "DIRECT_PLUS"])
def test_grace_exit_capitalizes_accrued_for_unsubsidized_and_plus(api, loan_type):
    """PRD §3.2: "the unsubsidized loan types — DIRECT_UNSUBSIDIZED
    and DIRECT_PLUS — have their accrued_interest_cents capitalized:
    the accrued amount is added to principal_balance_cents, the same
    amount is added to capitalized_interest_cents, and
    accrued_interest_cents is reset to 0."

    Claim: after grace exit principal grew by the accrued amount and
    accrued_interest_cents is zeroed.
    """
    b = create_borrower()
    loan, _ = create_loan_in_repayment(
        b["id"], loan_type=loan_type,
        original_principal_cents=1_000_000, interest_rate_bps=500,
    )
    assert loan["status"] == "REPAYMENT"
    assert loan["accrued_interest_cents"] == 0, (
        "PRD §3.2: accrued must be zeroed on capitalization at grace exit"
    )
    assert loan["principal_balance_cents"] > 1_000_000, (
        "PRD §3.2: capitalization must add accrued to principal"
    )
    # capitalized_interest_cents holds the same accrued amount.
    assert loan["capitalized_interest_cents"] == (
        loan["principal_balance_cents"] - 1_000_000
    ), (
        "PRD §3.2: capitalized_interest_cents must equal the amount "
        "added to principal on capitalization"
    )


def test_grace_exit_zero_accrued_for_subsidized(api):
    """PRD §3.2: "DIRECT_SUBSIDIZED loans carry no accrued interest
    out of grace because they were not accruing during the grace
    window."

    Claim: subsidized loan exits grace with accrued=0 and no
    capitalization bump on principal.
    """
    b = create_borrower()
    loan, _ = create_loan_in_repayment(
        b["id"], loan_type="DIRECT_SUBSIDIZED",
        original_principal_cents=1_000_000, interest_rate_bps=500,
    )
    assert loan["status"] == "REPAYMENT"
    assert loan["accrued_interest_cents"] == 0
    assert loan["principal_balance_cents"] == 1_000_000, (
        "PRD §3.2: subsidized loan has no capitalization at grace exit"
    )
    assert loan["capitalized_interest_cents"] == 0


# ---------------------------------------------------------------------------
# 3. Daily accrual rounding rules (PRD §3.3)
# ---------------------------------------------------------------------------
def test_per_call_rounding_not_per_day(api):
    """PRD §3.3: "the daily rate is computed as interest_rate_bps
    divided by 10000 and then divided by 365; the accrued amount for
    the call is the loan's current principal_balance_cents multiplied
    by that daily rate and by the elapsed-day count, rounded half-up
    to integer cents at that moment ... The rounding is performed
    once per loan per clock-advance call — neither per day individually
    nor after summing across loans."

    Claim: a single 30-day clock advance yields the per-call rounded
    value, not the sum of 30 per-day roundings.
    """
    reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
    b = create_borrower()
    loan = create_loan(b["id"], loan_type="DIRECT_UNSUBSIDIZED",
                       original_principal_cents=1_000_000,
                       interest_rate_bps=500)
    separate_loan(b["id"], loan["id"])  # IN_SCHOOL -> GRACE (accruing)
    advance_clock_by_days(30, from_stamp=TEST_DEFAULTS["INITIAL_CLOCK"])
    fetched = validate_success(
        api.get_loan(b["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    expected = round_half_up_to_int(1_000_000 * (500 / 10_000.0 / 365.0) * 30)
    assert fetched["accrued_interest_cents"] == expected
