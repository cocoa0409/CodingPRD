"""Pure functions: distance, peak windows, delivery fee, commission, fines, bonus tier."""
import math
from decimal import Decimal, ROUND_HALF_UP


EARTH_KM = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km, rounded to 1 decimal place."""
    r1, r2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(r1) * math.cos(r2) * math.sin(dlng / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    raw = EARTH_KM * c
    return float(Decimal(str(raw)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def is_peak_at(dt) -> bool:
    """11:00–13:00 UTC or 18:00–20:00 UTC (lower-bound inclusive, upper exclusive)."""
    h, m = dt.hour, dt.minute
    in_lunch = (11 <= h < 13) or (h == 13 and m == 0 and False)  # 11:00 through 13:00 inclusive of 11..12:59
    in_dinner = (18 <= h < 20)
    return (11 <= h < 13) or (18 <= h < 20)


def delivery_fee_solo(distance_km: float, is_peak: bool) -> int:
    """Base 300 + 120 per ceil(distance_km) band + 200 if peak."""
    bands = math.ceil(distance_km) if distance_km > 0 else 0
    fee = 300 + 120 * bands
    if is_peak:
        fee += 200
    return fee


def commission_tiered(subtotal_cents: int) -> int:
    """Marginal 15/18/22% across 20_000 and 50_000-cent caps. Half-up to whole cent, single pass."""
    tier1 = min(subtotal_cents, 20_000)
    tier2 = max(0, min(subtotal_cents, 50_000) - 20_000)
    tier3 = max(0, subtotal_cents - 50_000)
    total = (Decimal(tier1) * Decimal("0.15")
             + Decimal(tier2) * Decimal("0.18")
             + Decimal(tier3) * Decimal("0.22"))
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def commission_override(subtotal_cents: int, rate) -> int:
    """Flat-rate commission against the entire subtotal, half-up to whole cent."""
    total = Decimal(subtotal_cents) * Decimal(str(rate))
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def late_fine_amount(minutes_late: int, final_delivery_fee_cents: int) -> int:
    """Tiered late-fine amount per §3.7."""
    if minutes_late <= 0:
        return 0
    if 1 <= minutes_late <= 10:
        return 200
    if 11 <= minutes_late <= 30:
        return 500 + 50 * (minutes_late - 10)
    return min(final_delivery_fee_cents, 1500) + 500


def bonus_tier(on_time_rate: float, acceptance_rate: float, rating: float) -> str:
    score = (Decimal(str(on_time_rate)) * Decimal("0.6")
             + Decimal(str(acceptance_rate)) * Decimal("0.3")
             + (Decimal(str(rating)) / Decimal("5")) * Decimal("0.1"))
    score = score.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if score >= Decimal("0.900"):
        return "PLATINUM"
    if score >= Decimal("0.800"):
        return "GOLD"
    if score >= Decimal("0.700"):
        return "SILVER"
    return "BRONZE"


def merge_discount(solo_fee_cents: int) -> int:
    return math.floor(solo_fee_cents * 0.25)
