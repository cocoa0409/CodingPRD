"""Support-math calculations (PRD §2.8, §3.3, §3.4, §3.6; scaffold §1.3).

All money is whole integer cents. Rounding is half-up at every pinned step.
The parenting-time fraction is the one exception carried to four decimals
(also round half-up). Never use float for money math — use Decimal.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List


TOTAL_OVERNIGHTS = 365


def _round_cents(x: Decimal) -> int:
    """Round a Decimal to whole cents, half-up, returning an int."""
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def net_disposable_income(disclosure: Dict[str, Any]) -> int:
    """net = gross - (tax + retirement + health), floored at 0.

    Inputs are whole cents; the pinned order sums the three deduction lines
    first (in field order), subtracts from gross, then floors at 0 (PRD §3.3).
    """
    deductions = (
        int(disclosure["tax_withholding_cents"])
        + int(disclosure["mandatory_retirement_cents"])
        + int(disclosure["health_insurance_cents"])
    )
    net = int(disclosure["gross_monthly_income_cents"]) - deductions
    return max(0, net)


def parenting_time_percentage(petitioner_overnights: int) -> float:
    """petitioner_overnights / 365, rounded half-up to 4 decimals (PRD §3.4)."""
    pct = (Decimal(petitioner_overnights) / Decimal(TOTAL_OVERNIGHTS)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return float(pct)


def _select_tier(tiers: List[Dict[str, Any]], combined: int):
    """Pick the tier whose [min,max] band contains combined (both ends
    inclusive; a value equal to a tier's max belongs to that tier — ties
    resolve to the LOWER tier). Returns the tier dict or None.
    """
    for tier in tiers:
        lo = int(tier["min_combined_monthly_cents"])
        hi = int(tier["max_combined_monthly_cents"])
        if lo <= combined <= hi:
            return tier
    return None


def child_support(
    *,
    schedule: Dict[str, Any],
    child_count: int,
    payor_income: int,
    payee_income: int,
    payor_time_pct: float,
) -> int:
    """Compute a CHILD support monthly_amount_cents (PRD §3.6, scaffold §1.3).

    Steps (each rounded half-up to whole cents where noted):
      0. child_count == 0 -> 0 (empty-set boundary).
      1. combined = payor_income + payee_income (caller passes per-variant incomes).
      2. select tier by combined (inclusive both ends, ties to lower tier).
      3. base = tier.base_cents_one_child; if >1 child, scale up by
         (1 + marginal_pct_per_extra_child * (child_count - 1)), round half-up.
      4. prorate by payor income share: base * (payor / combined), round half-up.
      5. shared-custody offset: if payor_time_pct >= threshold (>=, not >),
         obligation *= (1 - payor_time_pct), round half-up.
      6. max(0, obligation).
    """
    if child_count == 0:
        return 0

    combined = payor_income + payee_income

    tier = _select_tier(schedule["basic_obligation_tiers"], combined)
    if tier is None:
        # No tier covers this income band; treat as zero obligation.
        return 0

    base = Decimal(int(tier["base_cents_one_child"]))
    if child_count > 1:
        marginal = Decimal(str(tier["marginal_pct_per_extra_child"]))
        factor = Decimal(1) + marginal * Decimal(child_count - 1)
        base = Decimal(_round_cents(base * factor))

    if combined <= 0:
        return 0

    payor_share = Decimal(payor_income) / Decimal(combined)
    obligation = Decimal(_round_cents(base * payor_share))

    threshold = Decimal(str(schedule["shared_custody_threshold_pct"]))
    payor_pct = Decimal(str(payor_time_pct))
    if payor_pct >= threshold:  # >=, NOT >
        obligation = Decimal(_round_cents(obligation * (Decimal(1) - payor_pct)))

    return max(0, int(obligation))


def spousal_support(
    *,
    schedule: Dict[str, Any],
    payor_income: int,
    payee_income: int,
    marriage_months: int,
) -> tuple:
    """Compute a SPOUSAL support (monthly_amount_cents, support_term_months).

    gross_obligation = round(payor_pct * payor_income
                             - payee_offset_pct * payee_income), half-up.
    monthly_amount_cents = max(0, gross_obligation).
    Term: marriage_months >= long_marriage_months -> 0 (INDEFINITE sentinel);
    else floor(marriage_months / 2) (PRD §3.6).
    """
    payor_pct = Decimal(str(schedule["spousal_payor_pct"]))
    payee_offset_pct = Decimal(str(schedule["spousal_payee_offset_pct"]))

    gross_obligation = _round_cents(
        payor_pct * Decimal(payor_income) - payee_offset_pct * Decimal(payee_income)
    )
    monthly_amount_cents = max(0, gross_obligation)

    long_marriage_months = int(schedule["long_marriage_months"])
    if marriage_months >= long_marriage_months:  # >=, NOT >
        support_term_months = 0  # INDEFINITE sentinel
    else:
        support_term_months = marriage_months // 2  # floor of half the marriage

    return monthly_amount_cents, support_term_months
