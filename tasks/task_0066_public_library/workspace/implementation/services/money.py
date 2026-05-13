"""Money helpers — Decimal arithmetic with HALF_UP rounding to whole cents."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value) -> int:
    """Round a number to the nearest integer cent using HALF_UP rounding."""
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# Daily fine rates by subject category (per PRD §3.6)
DAILY_RATE_BY_CATEGORY = {
    "GENERAL": 20,
    "REFERENCE": 50,
    "CHILDREN": 10,
    "RARE": 200,
}
FINE_CAP_BY_CATEGORY = {
    "GENERAL": 5000,
    "REFERENCE": 10000,
    "CHILDREN": 2000,
    "RARE": 50000,
}

# Card-derived attributes by card_type (PRD §3.2)
CARD_PROFILE = {
    "REGULAR":   {"max_loans": 5, "loan_duration_days": 30, "max_renewals": 2},
    "STUDENT":   {"max_loans": 8, "loan_duration_days": 60, "max_renewals": 3},
    "SENIOR":    {"max_loans": 4, "loan_duration_days": 45, "max_renewals": 2},
    "TEMPORARY": {"max_loans": 2, "loan_duration_days": 14, "max_renewals": 0},
}

# ILL settlement constants (PRD §3.7)
ILL_INSURANCE_RATE_BPS = 250  # 2.50%
ILL_HANDLING_FEE_CENTS = 300
ILL_REQUESTER_MAX_DAYS = 21


def ill_per_leg_total(shipping_cost_cents: int, handling_fee_cents: int) -> int:
    """Compute one leg total: round_half_up insurance first, then shipping+handling+insurance.

    insurance = round_half_up(shipping_cost_cents * 250 / 10000)
    per_leg   = round_half_up(shipping_cost_cents + handling_fee_cents + insurance)
    """
    s = Decimal(shipping_cost_cents)
    insurance = round_half_up(s * Decimal(ILL_INSURANCE_RATE_BPS) / Decimal(10000))
    per_leg = round_half_up(Decimal(shipping_cost_cents)
                            + Decimal(handling_fee_cents)
                            + Decimal(insurance))
    return per_leg


def ill_settlement_total(shipping_cost_cents: int, handling_fee_cents: int) -> int:
    """Symmetric two-leg total = sum of two independently rounded legs."""
    per_leg = ill_per_leg_total(shipping_cost_cents, handling_fee_cents)
    return per_leg + per_leg


# Loan / reservation constants
RECALL_GRACE_DAYS = 3
HOLD_PERIOD_DAYS = 2  # PRD §3.5: 48-hour hold = 2 days
