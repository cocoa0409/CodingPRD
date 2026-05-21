"""Calculation rules pinned in SCAFFOLD §1.3.

All monetary values are integer cents. Rounding direction is pinned per rule
and must not be silently changed.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Iterable, Tuple


DEPENDENT_ALLOWANCE_CENTS = 48000  # $480 per dependent
ELDERLY_ALLOWANCE_CENTS = 40000    # $400 once per qualifying household
WELFARE_RENT_CENTS = 0
MINIMUM_RENT_CENTS = 5000          # $50 statutory floor
RENT_BURDEN_NUMERATOR = 40         # 40 / 100
RENT_BURDEN_DENOMINATOR = 100
REASONABLENESS_NUMERATOR = 110     # 110 / 100 = 1.10


def calc_adjusted_income(
    *,
    gross_cents: int,
    dependents_count: int,
    elderly_or_disabled_head: bool,
    medical_expense_cents: int,
    childcare_expense_cents: int,
) -> int:
    """Variant-agnostic computation of adjusted annual income (integer cents).

    The caller supplies the proper inputs for each variant per scaffold:
      * initial: applicant.dependents_count, applicant.gross/medical/childcare
      * recertification: declared_household_size - 1, declared gross, applicant
        medical/childcare/elderly_flag (frozen)
    """
    if gross_cents < 0:
        gross_cents = 0
    if dependents_count < 0:
        dependents_count = 0

    dep_allowance = DEPENDENT_ALLOWANCE_CENTS * dependents_count
    elderly_allowance = ELDERLY_ALLOWANCE_CENTS if elderly_or_disabled_head else 0

    # Medical threshold uses floor(gross * 0.03).
    medical_threshold = (gross_cents * 3) // 100
    if elderly_or_disabled_head and medical_expense_cents > medical_threshold:
        medical_deduction = medical_expense_cents - medical_threshold
    else:
        medical_deduction = 0

    # Childcare is capped at gross (the scaffold's pinned simplification).
    childcare_deduction = min(max(childcare_expense_cents, 0), gross_cents)

    total_deductions = dep_allowance + elderly_allowance + medical_deduction + childcare_deduction
    adjusted = max(0, gross_cents - total_deductions)
    return adjusted


def calc_ttp(*, adjusted_annual_income_cents: int, gross_annual_income_cents: int) -> int:
    """Total Tenant Payment in cents (variant-agnostic).

    The rounding order is pinned: divide-then-floor first, then multiply-then-ceil.
    """
    monthly_adjusted = max(0, adjusted_annual_income_cents) // 12
    monthly_gross = max(0, gross_annual_income_cents) // 12

    thirty_pct = _ceil_div(monthly_adjusted * 30, 100)
    ten_pct = _ceil_div(monthly_gross * 10, 100)

    return max(thirty_pct, ten_pct, WELFARE_RENT_CENTS, MINIMUM_RENT_CENTS)


def calc_hap(*, applicable_payment_standard_cents: int, gross_rent_cents: int, ttp_cents: int) -> int:
    """HAP in cents — capped at zero, capped at min(PS, gross_rent) - TTP."""
    cap = min(applicable_payment_standard_cents, gross_rent_cents)
    return max(0, cap - ttp_cents)


def calc_rent_burden_passes(
    *,
    gross_rent_cents: int,
    initial_hap_cents: int,
    adjusted_annual_income_cents: int,
) -> Tuple[bool, str]:
    """Return (passes, error_id). The error_id is empty string when passes is True.

    Performs the comparison in exact integer arithmetic per scaffold:
        tenant_share * 100 <= 40 * monthly_adjusted
    The 40% cap is INCLUSIVE.

    When the monthly adjusted income evaluates to zero, returns
    (False, "ERR_RENT_BURDEN_DIVZERO") — a separate failure mode.
    """
    monthly_adjusted = max(0, adjusted_annual_income_cents) // 12
    if monthly_adjusted == 0:
        return False, "ERR_RENT_BURDEN_DIVZERO"
    tenant_share = gross_rent_cents - initial_hap_cents
    if tenant_share * RENT_BURDEN_DENOMINATOR <= RENT_BURDEN_NUMERATOR * monthly_adjusted:
        return True, ""
    return False, "ERR_RENT_BURDEN_EXCEEDED"


def calc_rent_burden_pct(
    *,
    gross_rent_cents: int,
    initial_hap_cents: int,
    adjusted_annual_income_cents: int,
) -> float:
    monthly_adjusted = max(0, adjusted_annual_income_cents) // 12
    if monthly_adjusted == 0:
        return 0.0
    tenant_share = gross_rent_cents - initial_hap_cents
    return tenant_share / monthly_adjusted


def calc_rent_reasonableness(comparables: Iterable[int]) -> Tuple[int, int]:
    """Return (median_comparable_cents, reasonable_threshold_cents).

    Even-N tie-break: lower of the two middles (NOT the arithmetic mean).
    Threshold = floor(median * 1.10).
    """
    arr = sorted(int(c) for c in comparables)
    n = len(arr)
    if n == 0:
        raise ValueError("comparables must not be empty")
    if n % 2 == 1:
        median = arr[(n - 1) // 2]
    else:
        median = arr[(n // 2) - 1]
    threshold = (median * REASONABLENESS_NUMERATOR) // 100
    return median, threshold


def _ceil_div(numerator: int, denominator: int) -> int:
    """Integer ceiling division (handles negatives by clamping to 0)."""
    if denominator <= 0:
        return 0
    if numerator <= 0:
        return 0
    return (numerator + denominator - 1) // denominator
