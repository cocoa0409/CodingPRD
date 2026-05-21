"""Numerical and time computations specified by the PRD."""

import math
from decimal import Decimal, ROUND_HALF_UP


# --- Geometry ---

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lng1, lat2, lng2):
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def distance_km_rounded(lat1, lng1, lat2, lng2):
    """Distance rounded half-up to one decimal place."""
    raw = haversine_km(lat1, lng1, lat2, lng2)
    return float(
        Decimal(repr(raw)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    )


def haversine_meters(lat1, lng1, lat2, lng2):
    return haversine_km(lat1, lng1, lat2, lng2) * 1000.0


# --- Peak windows ---

def is_peak_at(dt):
    """True when dt falls inside 11:00-13:00 UTC or 18:00-20:00 UTC.

    The window is closed on the left and open on the right: 11:00:00 is
    peak, 13:00:00 is not.
    """
    h = dt.hour
    return (11 <= h < 13) or (18 <= h < 20)


# --- Delivery fee ---

def solo_delivery_fee_cents(distance_km, is_peak):
    bands = math.ceil(distance_km)
    if bands < 0:
        bands = 0
    fee = 300 + bands * 120
    if is_peak:
        fee += 200
    return fee


def merge_discount_cents(solo_fee_cents):
    """Floor-rounded 25% route-merge discount."""
    return solo_fee_cents * 25 // 100  # integer floor


# --- Commission ---

_TIER1_CAP = 20000
_TIER2_CAP = 50000


def commission_tiered_cents(subtotal_cents):
    """Tiered marginal commission with single half-up rounding step."""
    t1 = min(subtotal_cents, _TIER1_CAP)
    t2 = max(0, min(subtotal_cents, _TIER2_CAP) - _TIER1_CAP)
    t3 = max(0, subtotal_cents - _TIER2_CAP)
    total = (
        Decimal(t1) * Decimal("0.15")
        + Decimal(t2) * Decimal("0.18")
        + Decimal(t3) * Decimal("0.22")
    )
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def commission_flat_cents(subtotal_cents, rate):
    """Flat override commission, half-up to whole cent."""
    total = Decimal(subtotal_cents) * Decimal(str(rate))
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def commission_cents(subtotal_cents, override_rate):
    if override_rate is None:
        return commission_tiered_cents(subtotal_cents)
    return commission_flat_cents(subtotal_cents, override_rate)


# --- Bonus tier ---

def bonus_tier_score(on_time_rate, acceptance_rate, rating):
    s = (
        Decimal(str(on_time_rate)) * Decimal("0.6")
        + Decimal(str(acceptance_rate)) * Decimal("0.3")
        + (Decimal(str(rating)) / Decimal("5")) * Decimal("0.1")
    )
    return float(s.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def bonus_tier(on_time_rate, acceptance_rate, rating):
    score = bonus_tier_score(on_time_rate, acceptance_rate, rating)
    if score >= 0.9:
        return "PLATINUM"
    if score >= 0.8:
        return "GOLD"
    if score >= 0.7:
        return "SILVER"
    return "BRONZE"


# --- Late fine amount ---

def late_fine_amount_cents(minutes_late, final_delivery_fee_cents):
    if minutes_late <= 0:
        return 0
    if minutes_late <= 10:
        return 200
    if minutes_late <= 30:
        return 500 + 50 * (minutes_late - 10)
    clawback = min(final_delivery_fee_cents, 1500)
    return clawback + 500
