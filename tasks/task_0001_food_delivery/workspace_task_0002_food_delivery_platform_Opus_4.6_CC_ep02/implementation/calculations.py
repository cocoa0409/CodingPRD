import math
from decimal import Decimal, ROUND_HALF_UP


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    return round(distance, 1)


def compute_delivery_fee(distance_km, is_peak):
    base = 300
    bands = math.ceil(distance_km)
    if bands < 0:
        bands = 0
    per_km = bands * 120
    peak = 200 if is_peak else 0
    return base + per_km + peak


def compute_tiered_commission(subtotal_cents):
    s = Decimal(str(subtotal_cents))
    tier1_amount = min(s, Decimal("20000"))
    tier2_amount = max(Decimal("0"), min(s, Decimal("50000")) - Decimal("20000"))
    tier3_amount = max(Decimal("0"), s - Decimal("50000"))

    total = (tier1_amount * Decimal("0.15")
             + tier2_amount * Decimal("0.18")
             + tier3_amount * Decimal("0.22"))

    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_flat_commission(subtotal_cents, rate):
    s = Decimal(str(subtotal_cents))
    r = Decimal(str(rate))
    total = s * r
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_final_delivery_fee(distance_km, is_peak, route_group, assignment_id):
    solo_fee = compute_delivery_fee(distance_km, is_peak)
    if route_group and len(route_group["assignment_ids"]) >= 2:
        discount = math.floor(solo_fee * 0.25)
        return solo_fee - discount
    return solo_fee


def compute_late_fine(minutes_late, final_delivery_fee_cents):
    if minutes_late <= 0:
        return 0
    if 1 <= minutes_late <= 10:
        return 200
    if 11 <= minutes_late <= 30:
        return 500 + 50 * (minutes_late - 10)
    return min(final_delivery_fee_cents, 1500) + 500


def compute_rider_score(on_time_rate, acceptance_rate, rating):
    raw = Decimal(str(0.6)) * Decimal(str(on_time_rate)) + \
          Decimal(str(0.3)) * Decimal(str(acceptance_rate)) + \
          Decimal(str(0.1)) * (Decimal(str(rating)) / Decimal("5"))
    score = raw.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return float(score)


def compute_bonus_tier(score):
    if score >= 0.90:
        return "PLATINUM"
    if score >= 0.80:
        return "GOLD"
    if score >= 0.70:
        return "SILVER"
    return "BRONZE"


def recompute_rider_bonus(rider):
    score = compute_rider_score(rider["on_time_rate"], rider["acceptance_rate"], rider["rating"])
    rider["bonus_tier"] = compute_bonus_tier(score)
