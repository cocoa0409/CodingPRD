"""Calculation rules (SCAFFOLD §1.3, PRD §2.8 / §3.4 / §3.7).

All monetary amounts are integer cents. Rounding is round-half-up at the points
pinned in the PRD. Decimal is used so the half-up rounding is exact (never float).
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---- adoption_fee constants ----
BASE_FEE_CENTS = {"PUPPY_KITTEN": 25000, "ADULT": 15000, "SENIOR": 5000}
MICROCHIP_SURCHARGE_CENTS = 2500
PROMO_PCT = Decimal("0.20")
PROMO_FLAT_CENTS = 3000
MIN_FEE_CENTS = 0

# ---- board cost constants ----
CARE_FEE_PCT = Decimal("0.075")
HOURS_PER_DAY = 24


def _round_half_up(value):
    """Round a Decimal to the nearest whole integer, half-up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def age_band(age_months):
    """PUPPY_KITTEN if < 6 months; SENIOR if >= 84 months; else ADULT."""
    if age_months < 6:
        return "PUPPY_KITTEN"
    if age_months >= 84:
        return "SENIOR"
    return "ADULT"


def adoption_fee_cents(age_months, microchipped, promo_active):
    """Tiered adoption fee in integer cents.

    Pinned evaluation order: age_band -> base -> microchip surcharge -> promo
    discount -> floor.
    """
    base = BASE_FEE_CENTS[age_band(age_months)]
    microchip_fee = 0 if microchipped else MICROCHIP_SURCHARGE_CENTS
    gross = base + microchip_fee
    if promo_active:
        pct_off = _round_half_up(Decimal(gross) * PROMO_PCT)  # nearest cent, half-up
        discount = max(PROMO_FLAT_CENTS, pct_off)
    else:
        discount = 0
    return max(MIN_FEE_CENTS, gross - discount)


def occupied_days(start_at, end_at):
    """Half-open [start_at, end_at) day count: ceil(hours/24), min 1."""
    elapsed = end_at - start_at
    hours = elapsed.total_seconds() / 3600.0
    days = math.ceil(hours / HOURS_PER_DAY)
    return max(1, days)


def daily_charged_cents(daily_base):
    """Per-day base plus 7.5% care fee, rounded half-up to whole cents (rounded FIRST)."""
    return _round_half_up(Decimal(daily_base) * (Decimal(1) + CARE_FEE_PCT))


def board_cost_cents(daily_base, start_at, end_at):
    """Round-per-day then multiply by day count (rounding order is pinned)."""
    days = occupied_days(start_at, end_at)
    return daily_charged_cents(daily_base) * days


def projected_board(daily_base, start_at, release_at):
    """Forward-looking projection to expected earliest release (stray_hold_release_at).

    Uses the same round-per-day rule but projects days from start_at to release_at.
    Returns (projected_board_cents, projected_occupied_days).
    """
    days = occupied_days(start_at, release_at)
    return daily_charged_cents(daily_base) * days, days


def stray_hold_release_at(source, intake_at, stray_hold_days):
    """STRAY: intake_at + stray_hold_days*24h. SURRENDER/TRANSFER: intake_at (zero hold)."""
    if source == "STRAY":
        return intake_at + timedelta(hours=stray_hold_days * HOURS_PER_DAY)
    return intake_at
