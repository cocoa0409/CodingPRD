"""Damage fee schedule: REPLACEMENT and DEPRECIATED variants (PRD §3.7).

Evaluation order is fixed: factor lookup -> multiply -> truncate toward zero
to integer cents -> deductible floor -> cap.
"""
from decimal import Decimal, ROUND_DOWN

FEE_CAP_CENTS = 50000
DEDUCTIBLE_CENTS = 5000

CONDITION_FACTOR = {
    "A": Decimal("1.00"),
    "B": Decimal("0.80"),
    "C": Decimal("0.60"),
    "F": Decimal("0.25"),
}


def age_factor(age_days):
    if age_days <= 365:
        return Decimal("1.0")
    if age_days <= 730:
        return Decimal("0.7")
    return Decimal("0.4")


def damage_fee_cents(base_value_cents, condition_factor, age_f):
    raw = Decimal(base_value_cents) * condition_factor * age_f
    raw_cents = int(raw.quantize(Decimal("1"), rounding=ROUND_DOWN))
    return min(FEE_CAP_CENTS, max(DEDUCTIBLE_CENTS, raw_cents))


def replacement_fee(base_value_cents):
    """REPLACEMENT variant: both factors forced to 1.0 (all provisional
    estimates, and LOST claims at assessment)."""
    return damage_fee_cents(base_value_cents, Decimal("1.0"), Decimal("1.0"))


def depreciated_fee(base_value_cents, condition_grade, age_days):
    """DEPRECIATED variant: full formula with assessed grade (DAMAGED claims)."""
    return damage_fee_cents(
        base_value_cents, CONDITION_FACTOR[condition_grade], age_factor(age_days)
    )
