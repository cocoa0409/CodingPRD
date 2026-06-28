"""Calculation rules from scaffold §1.3."""
from decimal import Decimal, ROUND_HALF_UP

# financial_aid_tier_banding constants
HOUSEHOLD_ALLOWANCE_CENTS = 600000
TIER_1_CEILING_CENTS = 6000000
TIER_2_CEILING_CENTS = 4000000
TIER_3_CEILING_CENTS = 2500000

# cycle_billing_amount constants
TIER_DISCOUNT = {
    "NONE": Decimal("0.00"),
    "TIER_1": Decimal("0.20"),
    "TIER_2": Decimal("0.40"),
    "TIER_3": Decimal("0.60"),
}

# match_score constants
SPECIALTY_WEIGHT = 10
STATE_WEIGHT = 25
SEVERITY_WEIGHT = 2

TOTAL_DAYS_PER_PERIOD = 7


def round_half_up(value):
    """Round a Decimal to whole cents (integer) using round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def band_aid_tier(annual_income_cents, household_size):
    adjusted = annual_income_cents - (household_size - 1) * HOUSEHOLD_ALLOWANCE_CENTS
    if adjusted < 0:
        adjusted = 0
    if adjusted < TIER_3_CEILING_CENTS:
        return "TIER_3"
    elif adjusted < TIER_2_CEILING_CENTS:
        return "TIER_2"
    elif adjusted < TIER_1_CEILING_CENTS:
        return "TIER_1"
    return "NONE"


def cycle_amounts(base_weekly_fee_cents, financial_aid_tier, wallet_credit_cents):
    """Returns (list_amount_cents, wallet_applied_cents, charged_amount_cents)."""
    discount_pct = TIER_DISCOUNT[financial_aid_tier]
    list_amount = round_half_up(Decimal(base_weekly_fee_cents) * (Decimal(1) - discount_pct))
    wallet_applied = min(wallet_credit_cents, list_amount)
    charged = list_amount - wallet_applied
    return list_amount, wallet_applied, charged


def pause_refund(paid_cents, elapsed_days):
    """Forward-looking proration. remaining_days = max(0, 7 - elapsed_days)."""
    remaining_days = max(0, TOTAL_DAYS_PER_PERIOD - elapsed_days)
    return round_half_up(Decimal(paid_cents) * Decimal(remaining_days) / Decimal(TOTAL_DAYS_PER_PERIOD))


def match_score(presenting_concerns, specialties, has_valid_license, severity_score):
    overlap = len(set(presenting_concerns) & set(specialties))
    return (SPECIALTY_WEIGHT * overlap
            + STATE_WEIGHT * (1 if has_valid_license else 0)
            + SEVERITY_WEIGHT * severity_score)
