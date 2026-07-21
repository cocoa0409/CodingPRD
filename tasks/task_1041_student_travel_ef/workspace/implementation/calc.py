"""Calculation rules. All money is integer cents; only rate multiplications
(early-bird discount, refund percentage) are rounded, half-up."""

import math
from decimal import Decimal, ROUND_HALF_UP

EARLY_BIRD_PCT = "0.10"
ADDON_PRICES = {"SINGLE_ROOM": 40000, "EXCURSION": 12000, "STEM_LAB": 8000}
INSURANCE_PREMIUMS = {"BASIC": 9900, "PREMIUM": 19900}
DEPOSIT_CENTS = 30000
DEFAULT_CHAPERONE_RATIO = 6
CHAPERONE_REST_BUFFER_DAYS = 1

# refund tiers keyed on whole days-before-departure
REFUND_PCT_90_PLUS = "1.00"
REFUND_PCT_60_89 = "0.75"
REFUND_PCT_30_59 = "0.50"
REFUND_PCT_UNDER_30 = "0.00"


def round_half_up_rate(base, pct_str):
    """round_half_up(base * pct) -> int cents."""
    return int((Decimal(base) * Decimal(pct_str)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def enrollment_price(gross, is_early_bird, add_ons, insurance_opted, insurance_tier):
    discount = round_half_up_rate(gross, EARLY_BIRD_PCT) if is_early_bird else 0
    add_ons_total = sum(ADDON_PRICES[a] for a in (add_ons or []))
    insurance = INSURANCE_PREMIUMS[insurance_tier] if insurance_opted else 0
    return gross - discount + add_ons_total + insurance


def installment_split(financed, n):
    """Floor each installment, then hand one leftover cent to the earliest
    installments. Sum is exactly `financed` (no drift)."""
    base_each = financed // n
    remainder = financed - base_each * n
    return [base_each + (1 if i < remainder else 0) for i in range(n)]


def days_before(depart_date, clock):
    """floor((depart_date - clock) / 1 day)."""
    delta = depart_date - clock
    return math.floor(delta.total_seconds() / 86400.0)


def refund_pct_str(days, insurance_opted, insurance_tier):
    if insurance_opted and insurance_tier == "PREMIUM":
        return "1.00"
    if days >= 90:
        return REFUND_PCT_90_PLUS
    if days >= 60:
        return REFUND_PCT_60_89
    if days >= 30:
        return REFUND_PCT_30_59
    return REFUND_PCT_UNDER_30


def refund_amount(refundable_base, pct_str):
    return round_half_up_rate(refundable_base, pct_str)


def free_spots(paying_count, chaperone_ratio):
    return paying_count // chaperone_ratio


def free_spot_credit(paying_count, chaperone_ratio, price_per_traveler_cents):
    return free_spots(paying_count, chaperone_ratio) * price_per_traveler_cents
