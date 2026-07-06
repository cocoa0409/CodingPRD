"""Calculation rules (PRD 2.5, 3.4, 3.5, 3.6, 3.9; scaffold Table 1.3).

All monetary amounts are integer cents. Rounding is round-half-up, applied only
at the points the PRD names and nowhere else. We use decimal.Decimal with
ROUND_HALF_UP for every rounding to avoid float error.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# Constants (scaffold Table 1.3).
MILEAGE_RATE_CENTS_PER_KM = 35
EARTH_RADIUS_KM = 6371.0088
CERT_PASS_THRESHOLD = 70
REJECT_RELIABILITY_PENALTY = 10
NO_SHOW_RELIABILITY_PENALTY = 20
MAX_REVISION_ROUNDS = 2
MAX_DISPUTE_ROUNDS = 3
IRS_1099_THRESHOLD_CENTS = 60000
TIER_HIGH_THRESHOLD = 90
TIER_MID_THRESHOLD = 75


def round_half_up(value):
    """Round a numeric value half-up to the nearest integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round to 2 decimal places, half-up. Returns a float."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def travel_distance_km(home_lat, home_lng, loc_lat, loc_lng):
    """Haversine great-circle distance home -> location (PRD 3.4)."""
    dlat = math.radians(loc_lat - home_lat)
    dlng = math.radians(loc_lng - home_lng)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(home_lat)) * math.cos(math.radians(loc_lat))
         * math.sin(dlng / 2) ** 2)
    dist = 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
    return round_half_up_2dp(dist)


def mileage_cents(distance_km):
    """Mileage component: round_half_up at the single multiply (PRD 2.5)."""
    return round_half_up(Decimal(str(distance_km)) * MILEAGE_RATE_CENTS_PER_KM)


def reimbursable(distance_km, oop_cents, reimburse_cap_cents):
    """capped_oop + mileage; cap is min(oop, cap); no further rounding (PRD 3.5/3.6)."""
    capped_oop = min(oop_cents, reimburse_cap_cents)
    return capped_oop + mileage_cents(distance_km)


def weighted_score(weights_json, section_scores_json, flagged_sections=None):
    """Weighted shop score.

    estimated (SELF_REPORT): every section counts at face value.
    audited (AUDITED): a section whose backing evidence is FLAGGED contributes 0,
        weights NOT renormalized.
    Sum first, round once half-up to an integer 0..100 (PRD 2.5/3.5/3.6).
    """
    flagged_sections = flagged_sections or set()
    total = Decimal("0")
    for section, weight in weights_json.items():
        if section in flagged_sections:
            continue
        raw = section_scores_json.get(section, 0)
        total += Decimal(str(weight)) * Decimal(str(raw))
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def shopper_fee(base_fee_cents, reliability_score):
    """base + round_half_up(base * bonus_pct); tier by >= (PRD 3.6)."""
    if reliability_score >= TIER_HIGH_THRESHOLD:
        bonus_pct = Decimal("0.20")
    elif reliability_score >= TIER_MID_THRESHOLD:
        bonus_pct = Decimal("0.10")
    else:
        bonus_pct = Decimal("0.00")
    bonus = round_half_up(Decimal(str(base_fee_cents)) * bonus_pct)
    return base_fee_cents + bonus


def crosses_1099(prior_ytd_cents, gross_amount_cents):
    """requires_1099 iff new_ytd >= threshold and prior_ytd < threshold (PRD 3.9)."""
    new_ytd = prior_ytd_cents + gross_amount_cents
    return new_ytd >= IRS_1099_THRESHOLD_CENTS and prior_ytd_cents < IRS_1099_THRESHOLD_CENTS
