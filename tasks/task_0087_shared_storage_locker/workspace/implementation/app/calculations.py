"""Domain calculations (PRD §3 / scaffold §1.3).

All monetary amounts are integer cents. We use Decimal with ROUND_HALF_UP for
the few half-up rounds the PRD requires, and ceil for hour/day rounding.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple

from . import constants
from .clock import add_seconds


# ---------------------------------------------------------------------------
# Rental fee
# ---------------------------------------------------------------------------


def rental_fee_cents(billing_units: int, unit_price_cents_snapshot: int) -> int:
    """rental_fee_cents = billing_units * unit_price_cents_snapshot. Integer math, no rounding."""
    return int(billing_units) * int(unit_price_cents_snapshot)


# ---------------------------------------------------------------------------
# Insurance premium (PRD §3.4)
# ---------------------------------------------------------------------------


def _ceil_int(value: float | Decimal) -> int:
    """Ceil to next integer; safe for float and Decimal."""
    if isinstance(value, Decimal):
        # Use Decimal to avoid float jitter.
        if value == value.to_integral_value():
            return int(value)
        return int(value.to_integral_value(rounding="ROUND_CEILING"))
    return int(math.ceil(value))


def rental_days_ceil(billing_units: int, rental_mode: str) -> int:
    seconds = int(billing_units) * constants.unit_duration_seconds(rental_mode)
    days = Decimal(seconds) / Decimal(constants.DAY_SECONDS)
    return _ceil_int(days)


def insurance_premium_cents(
    insurance_tier: str,
    declared_value_cents: int,
    billing_units: int,
    rental_mode: str,
) -> int:
    """PRD §3.4 — order: per-day base * days, then ceil(declared * loading_rate),
    then cap loading by tier cap, then sum."""
    tier = insurance_tier
    if tier == "NONE":
        return 0
    if tier == "BASIC":
        base_rate = constants.BASIC_BASE_RATE_CENTS_PER_DAY
        loading_rate = Decimal("0.002")
        loading_cap = constants.LOADING_CAP_BASIC
    elif tier == "PREMIUM":
        base_rate = constants.PREMIUM_BASE_RATE_CENTS_PER_DAY
        loading_rate = Decimal("0.005")
        loading_cap = constants.LOADING_CAP_PREMIUM
    else:
        # Shouldn't reach here — caller validates tier upfront.
        return 0

    days = rental_days_ceil(billing_units, rental_mode)
    tier_base = base_rate * days

    # Step 4: ceil(declared * loading_rate) — ceil AFTER multiplication.
    raw = Decimal(int(declared_value_cents)) * loading_rate
    value_loading = _ceil_int(raw)
    # Step 5: cap.
    value_loading = min(value_loading, loading_cap)

    return tier_base + value_loading


# ---------------------------------------------------------------------------
# Overdue fee accrual (PRD §3.3)
# ---------------------------------------------------------------------------


def grace_end(current_expires_at: datetime, grace_minutes_snapshot: int) -> datetime:
    return add_seconds(current_expires_at, grace_minutes_snapshot * 60)


def overdue_fee_cents(
    current_expires_at: datetime,
    grace_minutes_snapshot: int,
    overdue_rate_snapshot: int,
    as_of: datetime,
) -> int:
    """Compute the overdue fee at `as_of`.

    If `as_of` <= grace_end → 0. Otherwise: ceil(elapsed_seconds / 3600) * rate.
    Ceil applied BEFORE multiplication.
    """
    ge = grace_end(current_expires_at, grace_minutes_snapshot)
    if as_of <= ge:
        return 0
    elapsed = (as_of - ge).total_seconds()
    if elapsed <= 0:
        return 0
    hours = _ceil_int(Decimal(str(elapsed)) / Decimal(3600))
    return int(hours) * int(overdue_rate_snapshot)


# ---------------------------------------------------------------------------
# Deposit settlement (PRD §3.6 + §3.5)
# ---------------------------------------------------------------------------


def deposit_settle_return(deposit_cents_snapshot: int, overdue_fee: int) -> Tuple[int, int]:
    """Return-path: returns (deposit_refunded_cents, deposit_forfeited_cents)."""
    total = int(deposit_cents_snapshot)
    overdue = int(overdue_fee)
    if overdue <= total:
        return total - overdue, 0
    return 0, 0


def deposit_settle_force_clearance(deposit_cents_snapshot: int) -> Tuple[int, int]:
    """Force-clearance: full forfeit. Returns (refunded=0, forfeited=total)."""
    return 0, int(deposit_cents_snapshot)


# ---------------------------------------------------------------------------
# Revenue share split (PRD §2.12 / §3.6)
# ---------------------------------------------------------------------------


def revenue_split_per_row(gross_cents: int, partner_share_pct: int) -> Tuple[int, int]:
    """Per-row split: round_half_up partner share, residual = platform.

    Works for negative gross too (e.g., REFUND_REVERSAL). `round_half_up` on a
    negative goes toward zero on the .5 boundary — to keep "round half up"
    semantics consistent we apply half-up on absolute value then re-sign.
    Equivalently we use Decimal's ROUND_HALF_UP which rounds away from zero
    for positive values; for negatives the residual still balances. We
    standardize by rounding the partner_share with ROUND_HALF_UP and computing
    the platform residual.
    """
    gross = Decimal(int(gross_cents))
    pct = Decimal(int(partner_share_pct))
    # partner = round_half_up(gross * pct / 100)
    raw = gross * pct / Decimal(100)
    partner = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    platform = int(gross_cents) - partner
    return partner, platform


def revenue_aggregate_split(total_gross_cents: int, partner_share_pct: int) -> Tuple[int, int]:
    """Per-period aggregate split — round half-up after summation."""
    return revenue_split_per_row(total_gross_cents, partner_share_pct)


# ---------------------------------------------------------------------------
# Capacity stats / alert (PRD §3.7)
# ---------------------------------------------------------------------------


def percent_round_half_up_2dp(numerator: int, denominator: int) -> float:
    """Return 100 * num/den rounded half-up to 2 decimal places, as a float."""
    if denominator <= 0:
        return 0.0
    raw = (Decimal(int(numerator)) * Decimal(100)) / Decimal(int(denominator))
    quant = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(quant)


def level_for(pct: float) -> str:
    if pct >= constants.CRITICAL_PCT:
        return "CRITICAL"
    if pct >= constants.WARNING_PCT:
        return "WARNING"
    return "NONE"


def max_severity(*levels: str) -> str:
    rank = {"NONE": 0, "WARNING": 1, "CRITICAL": 2}
    best = "NONE"
    for lvl in levels:
        if rank[lvl] > rank[best]:
            best = lvl
    return best


# ---------------------------------------------------------------------------
# Haversine distance (PRD §3.7, redistribution)
# ---------------------------------------------------------------------------


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km, rounded to 4dp."""
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    dist = constants.EARTH_RADIUS_KM * c
    return round(dist, 4)
