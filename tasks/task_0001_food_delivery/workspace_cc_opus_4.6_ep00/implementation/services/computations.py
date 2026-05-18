import math
from decimal import Decimal, ROUND_HALF_UP


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    rlat1, rlng1 = math.radians(lat1), math.radians(lng1)
    rlat2, rlng2 = math.radians(lat2), math.radians(lng2)
    dlat = rlat2 - rlat1
    dlng = rlng2 - rlng1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    dist = R * c
    return round(dist, 1)


def is_peak_time(dt):
    hour = dt.hour
    return (11 <= hour < 13) or (18 <= hour < 20)


def compute_delivery_fee(distance_km, is_peak):
    base = 300
    bands = math.ceil(distance_km)
    per_km = bands * 120
    peak_surcharge = 200 if is_peak else 0
    return base + per_km + peak_surcharge


def compute_delivery_fee_with_merge(solo_fee, route_group, assignment_id):
    if route_group is None:
        return solo_fee
    if len(route_group["assignment_ids"]) < 2:
        return solo_fee
    discount = int(math.floor(solo_fee * 0.25))
    return solo_fee - discount


def compute_tiered_commission(subtotal_cents):
    s = Decimal(str(subtotal_cents))
    tier1_limit = Decimal("20000")
    tier2_limit = Decimal("50000")

    tier1_amount = min(s, tier1_limit)
    tier2_amount = min(s - tier1_amount, tier2_limit - tier1_limit)
    if tier2_amount < 0:
        tier2_amount = Decimal("0")
    tier3_amount = s - tier1_amount - tier2_amount
    if tier3_amount < 0:
        tier3_amount = Decimal("0")

    total = (
        tier1_amount * Decimal("0.15")
        + tier2_amount * Decimal("0.18")
        + tier3_amount * Decimal("0.22")
    )
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_commission(subtotal_cents, commission_rate_override):
    if commission_rate_override is not None:
        s = Decimal(str(subtotal_cents))
        rate = Decimal(str(commission_rate_override))
        total = s * rate
        return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return compute_tiered_commission(subtotal_cents)


def compute_late_fine(minutes_late, final_delivery_fee_cents):
    if minutes_late <= 0:
        return 0
    if minutes_late <= 10:
        return 200
    if minutes_late <= 30:
        return 500 + 50 * (minutes_late - 10)
    capped = min(final_delivery_fee_cents, 1500)
    return capped + 500


def compute_rider_score(on_time_rate, acceptance_rate, rating):
    raw = Decimal(str(on_time_rate)) * Decimal("0.6") + \
          Decimal(str(acceptance_rate)) * Decimal("0.3") + \
          (Decimal(str(rating)) / Decimal("5")) * Decimal("0.1")
    score = float(raw.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
    return score


def score_to_tier(score):
    if score >= 0.9:
        return "PLATINUM"
    if score >= 0.8:
        return "GOLD"
    if score >= 0.7:
        return "SILVER"
    return "BRONZE"


def recompute_bonus_tier(rider):
    score = compute_rider_score(
        rider["on_time_rate"], rider["acceptance_rate"], rider["rating"]
    )
    rider["bonus_tier"] = score_to_tier(score)
