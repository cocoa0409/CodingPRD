"""Calculation rules (SCAFFOLD 1.3 / PRD §2.7, §3). Pure functions only.

All decimal figures use decimal.Decimal with ROUND_HALF_UP at 2 places;
money stays integer cents; proportional shares floor.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# --- exposure_index constants ---
EXPOSURE_REVIEW_THRESHOLD = Decimal("10.00")
PROJECTION_HORIZON_YEARS = 5
RAIL_GROWTH_PCT = Decimal("0.02")
ROAD_GROWTH_PCT = Decimal("0.03")

# --- hazard_score constants ---
DEVICE_FACTOR = {
    "PASSIVE_CROSSBUCK": Decimal("1.50"),
    "FLASHING_LIGHTS": Decimal("1.20"),
    "GATES": Decimal("1.00"),
    "FOUR_QUADRANT_GATES": Decimal("0.90"),
}
INCIDENT_CAP = 5
INCIDENT_WEIGHT = 8
BUS_CAP = 20
BUS_WEIGHT = Decimal("0.5")
SIGHT_POOR_THRESHOLD = 2
SIGHT_POOR_MULTIPLIER = Decimal("1.15")
SCORE_CAP = Decimal("100")

# --- fra_reportable ---
FRA_DAMAGE_THRESHOLD_CENTS = 1_100_000

# --- match_split ---
FEDERAL_SHARE_PCT = Decimal("0.80")

# --- quiet_zone_risk ---
NSRT = Decimal("40.00")
MAX_SSM_CREDIT = Decimal("0.75")
SSM_EFFECTIVENESS = {
    "FOUR_QUADRANT_GATES": Decimal("0.82"),
    "MEDIANS": Decimal("0.40"),
    "CHANNELIZATION": Decimal("0.33"),
    "ONE_WAY_STREET": Decimal("0.25"),
    "WAYSIDE_HORN": Decimal("0.15"),
}

# --- closure_incentive_offer ---
BASE_CLOSURE_CENTS = 250_000
BASE_CONSOLIDATION_CENTS = 175_000
PER_EXPOSURE_POINT_CENTS = 5_000
EXPOSURE_INCENTIVE_CAP = Decimal("50.0")
MAX_INCENTIVE_CAP_CENTS = 1_000_000
MAX_NEGOTIATION_ROUNDS = 6

# --- preemption_timing_check ---
MIN_WARNING_SECONDS = 20
PREEMPTION_BUFFER_SECONDS = 5
OVERLAP_ALLOWANCE_SECONDS = 10


def q2(x):
    """Round half-up to exactly 2 decimal places."""
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def exposure_snapshot(annual_train_count, aadt):
    """round_half_up((annual_train_count/365)*aadt/1000, 2)."""
    trains_per_day = Decimal(annual_train_count) / Decimal(365)
    return q2(trains_per_day * Decimal(aadt) / Decimal(1000))


def exposure_projected(annual_train_count, aadt):
    """5-year compound-growth variant (2% rail / 3% road)."""
    projected_trains = Decimal(annual_train_count) * ((Decimal(1) + RAIL_GROWTH_PCT) ** PROJECTION_HORIZON_YEARS)
    projected_aadt = Decimal(aadt) * ((Decimal(1) + ROAD_GROWTH_PCT) ** PROJECTION_HORIZON_YEARS)
    return q2((projected_trains / Decimal(365)) * projected_aadt / Decimal(1000))


def exposure_band_multiplier(exposure_index):
    if exposure_index >= Decimal("25"):
        return Decimal("1.40")
    if exposure_index >= Decimal("10"):
        return Decimal("1.20")
    if exposure_index >= Decimal("3"):
        return Decimal("1.10")
    return Decimal("1.00")


def hazard_score(exposure_index, incident_count_5yr, school_bus_count,
                 sight_distance_rating, warning_device_class):
    band = exposure_band_multiplier(exposure_index)
    incident_term = Decimal(min(incident_count_5yr, INCIDENT_CAP) * INCIDENT_WEIGHT)
    bus_term = Decimal(min(school_bus_count, BUS_CAP)) * BUS_WEIGHT
    sight_mult = SIGHT_POOR_MULTIPLIER if sight_distance_rating <= SIGHT_POOR_THRESHOLD else Decimal("1.00")
    raw = (exposure_index * band + incident_term + bus_term) * DEVICE_FACTOR[warning_device_class] * sight_mult
    return q2(min(raw, SCORE_CAP))


def fra_reportable(fatalities, injuries, property_damage_cents):
    return (fatalities > 0) or (injuries > 0) or (property_damage_cents >= FRA_DAMAGE_THRESHOLD_CENTS)


def match_split(awarded_cents):
    """Per-award-line 80/20 split: federal rounded half-up first."""
    federal = int((Decimal(awarded_cents) * FEDERAL_SHARE_PCT).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return federal, awarded_cents - federal


def closure_incentive(closure_type, exposure_index):
    base = BASE_CLOSURE_CENTS if closure_type == "CLOSURE" else BASE_CONSOLIDATION_CENTS
    points = min(exposure_index, EXPOSURE_INCENTIVE_CAP)
    return base + int(points * PER_EXPOSURE_POINT_CENTS)


def ssm_credit(ssm_codes):
    total = Decimal(0)
    for code in ssm_codes:
        total += SSM_EFFECTIVENESS.get(code, Decimal(0))
    return min(total, MAX_SSM_CREDIT)


def riwh_indices(member_hazards_with_ssm):
    """member_hazards_with_ssm: list of (hazard_score Decimal, ssm_codes list).
    Returns (riwh_pre_ssm, riwh_post_ssm), both round-half-up 2dp."""
    n = len(member_hazards_with_ssm)
    pre_total = Decimal(0)
    post_total = Decimal(0)
    for hazard, ssm_codes in member_hazards_with_ssm:
        pre_total += hazard
        post_total += hazard * (Decimal(1) - ssm_credit(ssm_codes))
    pre = q2(pre_total / Decimal(n))
    post = q2(post_total / Decimal(n))
    return pre, post


def quiet_zone_decision(riwh_pre_ssm, riwh_post_ssm):
    """Pinned evaluation order: pre-check, then post-check, then progress check."""
    if riwh_pre_ssm <= NSRT or riwh_post_ssm <= NSRT:
        return "APPROVED"
    if riwh_post_ssm < riwh_pre_ssm:
        return "SUPPLEMENT_REQUIRED"
    return "REJECTED"


def preemption_timing(track_approach_distance_ft, design_train_speed_mph,
                      clear_storage_distance_ft, advance_preemption_seconds,
                      track_clearance_green_seconds):
    """Integer-second ceil arithmetic (exact rational math to avoid float error).

    approach_seconds = ceil(dist / (speed * 1.46667)) with 1.46667 = 146667/100000.
    """
    numerator = track_approach_distance_ft * 100000
    denominator = design_train_speed_mph * 146667
    approach_seconds = -(-numerator // denominator)
    required_clearance_green_seconds = -(-clear_storage_distance_ft * 10 // 150)  # ceil(d / 15.0)
    required_advance_preemption_seconds = max(
        0,
        required_clearance_green_seconds + PREEMPTION_BUFFER_SECONDS - OVERLAP_ALLOWANCE_SECONDS,
    )
    timing_check_pass = (
        approach_seconds >= MIN_WARNING_SECONDS
        and track_clearance_green_seconds >= required_clearance_green_seconds
        and advance_preemption_seconds >= required_advance_preemption_seconds
    )
    return {
        "approach_seconds": approach_seconds,
        "required_clearance_green_seconds": required_clearance_green_seconds,
        "required_advance_preemption_seconds": required_advance_preemption_seconds,
        "timing_check_pass": timing_check_pass,
    }


def windows_overlap(start_a, end_a, start_b, end_b):
    """Half-open [start, end) overlap; adjacency (end == start) is allowed."""
    return start_a < end_b and start_b < end_a
