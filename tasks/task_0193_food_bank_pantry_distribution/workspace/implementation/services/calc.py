"""Calculation rules (§1.3 / PRD §3). Poundage rounded 2dp ROUND_HALF_UP;
fair-share cap is integer pounds floored; TEFAP income test in integer cents."""
import math
from decimal import Decimal, ROUND_HALF_UP

# TEFAP income-eligibility constants (§1.3 tefap_income_eligibility / PRD §3.3)
TEFAP_BASE_CENTS = 199800
TEFAP_PER_PERSON_CENTS = 70500


def round2(value):
    """Round a numeric to 2 decimal places, round-half-up. Returns a float
    suitable for JSON (e.g. 12.5 -> 12.5, 12.345 -> 12.35)."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Normalize to int when whole, else float.
    return float(d)


def tefap_threshold_cents(household_size):
    return TEFAP_BASE_CENTS + (household_size - 1) * TEFAP_PER_PERSON_CENTS


def tefap_eligible(household_size, monthly_income_cents):
    return monthly_income_cents <= tefap_threshold_cents(household_size)


def fair_share_cap_lbs(total_pool_lbs, fair_share_weight, total_fair_share_weight):
    """cap_lbs = floor(total_pool_lbs * (weight / total_weight)) — integer pounds."""
    if total_fair_share_weight <= 0:
        return 0
    product = Decimal(str(total_pool_lbs)) * (
        Decimal(fair_share_weight) / Decimal(total_fair_share_weight)
    )
    return int(math.floor(product))
