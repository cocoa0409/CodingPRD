"""Calculation rules from SCAFFOLD §1.3.

All money stays in integer cents (PRD §2.5). The one non-integer quantity in the
system is the income/poverty-guideline ratio used in frl_tier_classification.
"""

from services.constants import (
    FEDERAL_POVERTY_GUIDELINE_BY_SIZE,
    FREE_THRESHOLD_RATIO,
    REDUCED_THRESHOLD_RATIO,
    REDUCED_COPAY_CENTS,
    USDA_FREE_RATE_CENTS,
    USDA_REDUCED_RATE_CENTS,
    USDA_PAID_RATE_CENTS,
    HIGH_SODIUM_THRESHOLD_MG,
)


def frl_tier_classification(declared_annual_income_cents: int,
                            household_size: int) -> str:
    """Map (income, household_size) to FREE | REDUCED | DENIED_PAID.

    Per PRD §3.4: ratio is floating-point, both upper bounds non-strict.
    """
    guideline = FEDERAL_POVERTY_GUIDELINE_BY_SIZE[household_size]
    ratio = declared_annual_income_cents / guideline
    if ratio <= FREE_THRESHOLD_RATIO:
        return "FREE"
    if ratio <= REDUCED_THRESHOLD_RATIO:
        return "REDUCED"
    return "DENIED_PAID"


def meal_charge_calc(tier_at_serving: str, menu_item_full_price_cents: int) -> int:
    """Per-meal charge to the parent account. Integer cents."""
    if tier_at_serving == "FREE":
        return 0
    if tier_at_serving == "REDUCED":
        return REDUCED_COPAY_CENTS
    # PAID
    return menu_item_full_price_cents


def usda_reimbursement_provisional(tier_at_serving: str,
                                   menu_item_reimbursable: bool) -> int:
    """Forward-looking reimbursement stamped at SERVED time. Never recomputed."""
    if not menu_item_reimbursable:
        return 0
    if tier_at_serving == "FREE":
        return USDA_FREE_RATE_CENTS
    if tier_at_serving == "REDUCED":
        return USDA_REDUCED_RATE_CENTS
    return USDA_PAID_RATE_CENTS


def usda_rate_for_tier(eff_tier: str, reimbursable: bool) -> int:
    """Same as provisional but parameterised by an arbitrary tier."""
    if not reimbursable:
        return 0
    if eff_tier == "FREE":
        return USDA_FREE_RATE_CENTS
    if eff_tier == "REDUCED":
        return USDA_REDUCED_RATE_CENTS
    return USDA_PAID_RATE_CENTS


def high_sodium_flag(sodium_mg: int) -> bool:
    """Non-strict comparison: >= 600 mg is flagged."""
    return sodium_mg >= HIGH_SODIUM_THRESHOLD_MG
