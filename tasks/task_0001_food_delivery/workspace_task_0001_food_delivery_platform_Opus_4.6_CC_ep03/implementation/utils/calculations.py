import math
from decimal import Decimal, ROUND_HALF_UP


def haversine_raw(lat1, lng1, lat2, lng2):
    R = 6371.0
    lat1_r, lng1_r = math.radians(lat1), math.radians(lng1)
    lat2_r, lng2_r = math.radians(lat2), math.radians(lng2)
    dlat = lat2_r - lat1_r
    dlng = lng2_r - lng1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def haversine_km(lat1, lng1, lat2, lng2):
    return round(haversine_raw(lat1, lng1, lat2, lng2), 1)


def compute_delivery_fee(distance_km, is_peak):
    base = 300
    bands = math.ceil(distance_km) if distance_km > 0 else 0
    per_km = bands * 120
    peak = 200 if is_peak else 0
    return base + per_km + peak


def compute_tiered_commission(subtotal_cents):
    tier1_cap = 20000
    tier2_cap = 50000
    tier1_amount = min(subtotal_cents, tier1_cap)
    tier2_amount = max(0, min(subtotal_cents, tier2_cap) - tier1_cap)
    tier3_amount = max(0, subtotal_cents - tier2_cap)
    total = (Decimal(str(tier1_amount)) * Decimal('0.15') +
             Decimal(str(tier2_amount)) * Decimal('0.18') +
             Decimal(str(tier3_amount)) * Decimal('0.22'))
    return int(total.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def compute_flat_commission(subtotal_cents, rate):
    total = Decimal(str(subtotal_cents)) * Decimal(str(rate))
    return int(total.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def is_peak_time(dt):
    hour = dt.hour
    return (11 <= hour < 13) or (18 <= hour < 20)


def compute_late_fine(minutes_late, final_delivery_fee_cents):
    if minutes_late <= 0:
        return 0
    if minutes_late <= 10:
        return 200
    if minutes_late <= 30:
        return 500 + 50 * (minutes_late - 10)
    return min(final_delivery_fee_cents, 1500) + 500


def compute_bonus_score(on_time_rate, acceptance_rate, rating):
    score = 0.6 * on_time_rate + 0.3 * acceptance_rate + 0.1 * (rating / 5.0)
    d = Decimal(str(score)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
    return float(d)


def score_to_tier(score):
    if score >= 0.90:
        return 'PLATINUM'
    if score >= 0.80:
        return 'GOLD'
    if score >= 0.70:
        return 'SILVER'
    return 'BRONZE'
