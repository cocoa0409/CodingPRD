"""Calculation rules (scaffold §1.3 / PRD §3.6, §3.7, §4 settlement)."""
import math
from decimal import Decimal, ROUND_HALF_UP

# Shipping constants (calculations.pledge_total)
DOMESTIC_BASE_CENTS = 500
DOMESTIC_PER_KG_CENTS = 150
INTL_BASE_CENTS = 1500
INTL_PER_KG_CENTS = 400
SHIPPING_CAP_CENTS = 5000

# platform_fee
FEE_RATE = Decimal("0.05")

# reliability
BASE_SCORE = 100.0

# tier_window_overlap
TIER_GAP_SECONDS = 3600


def round_half_up_cents(value):
    """Round a Decimal to whole cents, half-up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    """Round to 1 decimal place half-up. Returns float."""
    q = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(q)


def shipping_cents(total_weight_grams, destination_zone):
    """Zone base + per-kg surcharge (ceil to whole kg), capped (calculations.pledge_total)."""
    billable_kg = math.ceil(total_weight_grams / 1000)
    if destination_zone == "DOMESTIC":
        ship = DOMESTIC_BASE_CENTS + billable_kg * DOMESTIC_PER_KG_CENTS
    else:  # INTL
        ship = INTL_BASE_CENTS + billable_kg * INTL_PER_KG_CENTS
    return min(ship, SHIPPING_CAP_CENTS)


def per_pledge_fee_cents(committed_amount_cents):
    """Per-captured-pledge fee = committed * FEE_RATE, rounded half-up to whole cents."""
    return round_half_up_cents(Decimal(committed_amount_cents) * FEE_RATE)
