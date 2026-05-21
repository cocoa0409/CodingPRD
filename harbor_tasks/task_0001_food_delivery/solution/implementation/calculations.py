"""Business calculations: fees, commissions, fines, bonus tier, distance."""
import math
from decimal import Decimal
from common import round_half_up_to_int, round_half_up_to_places, floor_to_int


BASE_CENTS = 300
PER_KM_CENTS = 120
PEAK_CENTS = 200
ROUTE_MERGE_DISCOUNT_RATE = Decimal("0.25")

TIER1_CAP_CENTS = 20000
TIER2_CAP_CENTS = 50000
TIER1_RATE = Decimal("0.15")
TIER2_RATE = Decimal("0.18")
TIER3_RATE = Decimal("0.22")


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in kilometres."""
    R = 6371.0088  # Earth radius km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def distance_km_rounded(lat1, lon1, lat2, lon2) -> float:
    """Compute haversine distance and round to 1 decimal place (half-up)."""
    raw = haversine_km(lat1, lon1, lat2, lon2)
    d = round_half_up_to_places(raw, 1)
    return float(d)


def is_peak_time(dt) -> bool:
    """Peak windows: 11:00-13:00 UTC and 18:00-20:00 UTC."""
    h = dt.hour
    return (11 <= h < 13) or (18 <= h < 20)


def provisional_delivery_fee(distance_km: float, is_peak: bool) -> int:
    distance_units = math.ceil(distance_km)
    distance_surcharge = distance_units * PER_KM_CENTS
    peak_surcharge = PEAK_CENTS if is_peak else 0
    return BASE_CENTS + distance_surcharge + peak_surcharge


def final_delivery_fee(distance_km: float, is_peak: bool, route_group_size: int) -> int:
    """Compute final rider delivery fee. route_group_size == size of group if merged, else 1/0."""
    solo_fee = provisional_delivery_fee(distance_km, is_peak)
    if route_group_size >= 2:
        discount = floor_to_int(Decimal(solo_fee) * ROUTE_MERGE_DISCOUNT_RATE)
        return solo_fee - discount
    return solo_fee


def tiered_commission(subtotal_cents: int) -> int:
    t1 = min(subtotal_cents, TIER1_CAP_CENTS)
    t2 = max(0, min(subtotal_cents, TIER2_CAP_CENTS) - TIER1_CAP_CENTS)
    t3 = max(0, subtotal_cents - TIER2_CAP_CENTS)
    total = (Decimal(t1) * TIER1_RATE) + (Decimal(t2) * TIER2_RATE) + (Decimal(t3) * TIER3_RATE)
    return round_half_up_to_int(total)


def flat_commission(subtotal_cents: int, rate) -> int:
    return round_half_up_to_int(Decimal(subtotal_cents) * Decimal(str(rate)))


def final_commission(subtotal_cents: int, commission_rate_override) -> int:
    if commission_rate_override is not None:
        return flat_commission(subtotal_cents, commission_rate_override)
    return tiered_commission(subtotal_cents)


def late_delivery_fine(minutes_late: int, final_delivery_fee_cents: int) -> int:
    m = minutes_late
    if m <= 10:
        return 200
    elif m <= 30:
        return 500 + 50 * (m - 10)
    else:
        return min(final_delivery_fee_cents, 1500) + 500


def compute_bonus_tier(on_time_rate, acceptance_rate, rating) -> str:
    score = round_half_up_to_places(
        Decimal("0.6") * Decimal(str(on_time_rate))
        + Decimal("0.3") * Decimal(str(acceptance_rate))
        + Decimal("0.1") * (Decimal(str(rating)) / Decimal("5.0")),
        3,
    )
    if score >= Decimal("0.90"):
        return "PLATINUM"
    if score >= Decimal("0.80"):
        return "GOLD"
    if score >= Decimal("0.70"):
        return "SILVER"
    return "BRONZE"
