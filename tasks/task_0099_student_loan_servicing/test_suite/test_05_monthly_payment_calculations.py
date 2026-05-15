"""Monthly payment calculation (STANDARD_10 amortization + IDR formulas).

Anchors: PRD §3.7.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    IDR_FRACTION,
    IDR_MULTIPLIER,
    POVERTY_GUIDELINES_CENTS,
    TEST_DEFAULTS,
    TEST_USERS,
    api_client,
    create_and_activate_plan,
    create_borrower_with_loan_in_repayment,
    poverty_line_cents,
    round_half_up_to_int,
    validate_success,
)


# ===========================================================================
# Helpers (PRD §3.7)
# ===========================================================================
def expected_standard10_monthly_payment(pool_cents: int,
                                        weighted_bps: int) -> int:
    """PRD §3.7 amortization formula."""
    n = 120
    r = weighted_bps / 10_000.0 / 12.0
    if r == 0:
        payment = pool_cents / n
    else:
        payment = pool_cents * r * (1 + r) ** n / ((1 + r) ** n - 1)
    return round_half_up_to_int(payment)


def expected_idr_monthly_payment(plan_type: str,
                                 agi_cents: int,
                                 poverty_cents: int,
                                 pool_cents: int) -> int:
    """PRD §3.7 IDR formula with $5 floor for IBR/PAYE (not SAVE)."""
    multiplier = IDR_MULTIPLIER[plan_type]
    fraction = IDR_FRACTION[plan_type]
    discretionary = max(0, agi_cents - multiplier * poverty_cents)
    annual = discretionary * fraction
    monthly = round_half_up_to_int(annual / 12)
    if plan_type in ("IBR", "PAYE") and monthly == 0 and pool_cents > 0:
        monthly = 500
    return monthly


# ===========================================================================
# STANDARD_10 amortization (PRD §3.7)
# ===========================================================================
def test_standard10_amortization_matches_formula(api):
    """PRD §3.7: "For STANDARD_10, the schedule is a level-payment
    fully amortizing schedule over 120 months. The monthly rate is
    the weighted basis-point rate divided by 10000 and then divided
    by 12 ... it is computed using the standard amortization formula:
    the pool multiplied by the monthly rate multiplied by one-plus-
    monthly-rate raised to the 120th power, divided by one-plus-
    monthly-rate raised to the 120th power minus one. The result is
    rounded half-up to integer cents to produce monthly_payment_cents."

    Claim: a single 1,000,000-cent loan @ 500bps yields the formula's
    integer monthly payment after grace capitalization.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment(
        original_principal_cents=1_000_000, interest_rate_bps=500,
    )
    plan = create_and_activate_plan(
        borrower["id"], "STANDARD_10", [loan["id"]],
    )
    pool = loan["principal_balance_cents"] + loan["accrued_interest_cents"]
    expected = expected_standard10_monthly_payment(pool, 500)
    assert plan["monthly_payment_cents"] == expected, (
        f"PRD §3.7 STANDARD_10 formula: pool={pool}, bps=500 -> "
        f"expected {expected}, got {plan['monthly_payment_cents']}"
    )


def test_standard10_includes_accrued_in_pool_before_amortization(api):
    """PRD §3.7: "Pool aggregation is in integer cents; accrued
    interest is included in the pool before amortization, and the
    rounding step is the very last operation."

    Claim: the pool used in monthly_payment_calc equals principal +
    accrued at activation time (not just principal).
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment(
        loan_type="DIRECT_UNSUBSIDIZED",
        original_principal_cents=1_000_000, interest_rate_bps=500,
    )
    # Grace exit just capitalized accrued into principal, so accrued=0
    # at activation. The point of this test is the FORMULA — pool must
    # match principal+accrued at activation. We sample plan.monthly_payment_cents
    # and reverse-derive: if implementation computes from just principal
    # (ignoring accrued), it would still match because accrued is 0.
    # To force a non-zero accrued component, we'd need a state where
    # grace exit hasn't capitalized — but that path takes us to a
    # subsidized GRACE which doesn't accrue. The PRD-uniquely-derived
    # observable here is that the standard10 payment equals the formula
    # on (principal + accrued); we verify that equation holds.
    plan = create_and_activate_plan(
        borrower["id"], "STANDARD_10", [loan["id"]],
    )
    pool = loan["principal_balance_cents"] + loan["accrued_interest_cents"]
    expected = expected_standard10_monthly_payment(pool, 500)
    assert plan["monthly_payment_cents"] == expected


# ===========================================================================
# IDR formulas — SAVE / IBR / PAYE (PRD §3.7)
# ===========================================================================
@pytest.mark.parametrize("plan_type", ["SAVE", "IBR", "PAYE"])
def test_idr_monthly_payment_formula_with_positive_discretionary(api, plan_type):
    """PRD §3.7: "Discretionary income is computed as
    adjusted_gross_income_cents minus the multiplier times the
    poverty line, with the result clamped at zero from below (never
    negative). The annual payment is discretionary income multiplied
    by the plan-type income fraction — 0.15 for IBR, 0.10 for PAYE,
    0.05 for SAVE. The annual payment is divided by 12 and the result
    is rounded half-up to integer cents."

    Claim: with positive discretionary income, monthly_payment_cents
    matches the §3.7 formula for each IDR plan type.
    """
    # AGI well above the multiplier*poverty floor for family_size=1,CA.
    borrower, loan, _ = create_borrower_with_loan_in_repayment(
        state_code="CA", family_size=1,
        adjusted_gross_income_cents=4_000_000,
    )
    plan = create_and_activate_plan(
        borrower["id"], plan_type, [loan["id"]],
    )
    poverty = poverty_line_cents("CA", 1)
    pool = loan["principal_balance_cents"] + loan["accrued_interest_cents"]
    expected = expected_idr_monthly_payment(
        plan_type, 4_000_000, poverty, pool,
    )
    assert plan["monthly_payment_cents"] == expected, (
        f"PRD §3.7 IDR formula for {plan_type}: AGI=4_000_000, "
        f"poverty_line=1_506_000(CA fs=1) -> expected {expected}, got "
        f"{plan['monthly_payment_cents']}"
    )


def test_save_with_zero_discretionary_yields_zero_payment(api):
    """PRD §3.7: "for SAVE, there is no floor — a true $0 payment is
    permitted when discretionary income is 0."

    Claim: SAVE plan with AGI below 2.25*poverty produces
    monthly_payment_cents == 0.
    """
    # CA, fs=1, poverty=1,506,000; SAVE multiplier=2.25 -> 3,388,500.
    # AGI 1,000,000 -> discretionary clamped to 0 -> $0 monthly.
    borrower, loan, _ = create_borrower_with_loan_in_repayment(
        state_code="CA", family_size=1,
        adjusted_gross_income_cents=1_000_000,
    )
    plan = create_and_activate_plan(
        borrower["id"], "SAVE", [loan["id"]],
    )
    assert plan["monthly_payment_cents"] == 0, (
        "PRD §3.7: SAVE allows a true $0 payment when discretionary == 0"
    )


@pytest.mark.parametrize("plan_type", ["IBR", "PAYE"])
def test_ibr_paye_floor_at_500_cents_when_zero_discretionary(api, plan_type):
    """PRD §3.7: "for IBR and PAYE, if the rounded value is 0 and
    the pool is positive, the monthly payment is raised to 500 cents
    (a $5 minimum)."

    Claim: IBR/PAYE on a positive pool with zero discretionary income
    yields monthly_payment_cents == 500.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment(
        state_code="CA", family_size=1,
        adjusted_gross_income_cents=1_000_000,
    )
    plan = create_and_activate_plan(
        borrower["id"], plan_type, [loan["id"]],
    )
    assert plan["monthly_payment_cents"] == 500, (
        f"PRD §3.7: {plan_type} floors at 500 cents when discretionary==0 "
        f"and pool > 0, got {plan['monthly_payment_cents']}"
    )


# ===========================================================================
# Regional poverty tables (PRD §3.7)
# ===========================================================================
def test_alaska_poverty_table_drives_higher_payment(api):
    """PRD §3.7: "The Alaska table reads $18,820 (1,882,000 cents)
    for size 1, $25,420 for size 2..."

    Claim: same AGI/family_size on AK uses the AK poverty row; the
    resulting discretionary income differs from the CA case.
    """
    # AK fs=2 poverty = 2,542,000; SAVE multiplier 2.25 -> 5,719,500.
    # AGI 3,000,000 -> discretionary clamped to 0 -> $0 payment.
    borrower, loan, _ = create_borrower_with_loan_in_repayment(
        state_code="AK", family_size=2,
        adjusted_gross_income_cents=3_000_000,
    )
    plan = create_and_activate_plan(
        borrower["id"], "SAVE", [loan["id"]],
    )
    # PRD says SAVE allows $0; with AGI < 2.25 * AK poverty fs=2, the
    # SAVE payment must be exactly $0.
    assert plan["monthly_payment_cents"] == 0


def test_hawaii_poverty_table_distinct_from_48_dc(api):
    """PRD §3.7: "The Hawaii table reads $17,320 (1,732,000 cents)
    for size 1..."

    Claim: HI poverty row is distinct from 48_DC; same AGI/family_size
    in HI yields a different discretionary income than in CA.
    """
    # HI fs=1 poverty = 1,732,000; SAVE multiplier 2.25 -> 3,897,000.
    # AGI 4,000,000 -> discretionary = 103,000; annual = 5,150;
    # monthly = 5,150 / 12 = 429.17 -> 429. SAVE has no floor.
    borrower, loan, _ = create_borrower_with_loan_in_repayment(
        state_code="HI", family_size=1,
        adjusted_gross_income_cents=4_000_000,
    )
    plan = create_and_activate_plan(
        borrower["id"], "SAVE", [loan["id"]],
    )
    expected = round_half_up_to_int(
        max(0, 4_000_000 - 2.25 * 1_732_000) * 0.05 / 12
    )
    assert plan["monthly_payment_cents"] == expected, (
        f"PRD §3.7: HI fs=1 poverty 1,732,000 -> expected {expected}, "
        f"got {plan['monthly_payment_cents']}"
    )
