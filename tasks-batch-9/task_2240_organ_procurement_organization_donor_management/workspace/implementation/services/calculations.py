"""Pure calculation rules (SCAFFOLD calculations, PRD 2.6 / 3.x)."""

import math
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    BASE_PREP_MINUTES,
    CRASH_PREP_MINUTES,
    DECOMPENSATING_CEILING,
    EXPEDITED_PREP_MINUTES,
    EXPEDITED_TIER_FLOOR,
    FACTOR_WEIGHTS,
    IMPUTATION_FRACTION,
    MIN_POSTURE_SAMPLE,
    OPTIMIZED_FLOOR,
    POSTURE_GOOD_FLOOR,
    POSTURE_WATCH_FLOOR,
    PRESSOR_PENALTY_CAP,
    PRESSOR_PENALTY_PER_AGENT,
    RELIABILITY_MULTIPLIER,
    RISK_FACTORS,
    RISK_TIER_THRESHOLD,
    SCORE_CAP,
    STANDARD_PREP_MINUTES,
    STANDARD_TIER_FLOOR,
)

TWO_PLACES = Decimal("0.01")


def round2(value):
    """Decimal ROUND_HALF_UP to exactly two decimal places (PRD 2.6)."""
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def floor_minutes(later, earlier):
    """Whole minutes, truncated downward (PRD 2.6). 119 seconds is one minute."""
    return int(math.floor((later - earlier).total_seconds() / 60.0))


# --------------------------------------------------------- referral_timeliness_lag
def referral_timeliness(referred_at, trigger_event_at, death_pronounced_at, window_minutes):
    """Returns (referral_lag_minutes, timeliness_flag, audit_lag_minutes)."""
    referral_lag = floor_minutes(referred_at, trigger_event_at)
    flag = "TIMELY" if referral_lag <= window_minutes else "UNTIMELY"
    audit_lag = None
    if death_pronounced_at is not None:
        audit_lag = floor_minutes(referred_at, death_pronounced_at)
    return referral_lag, flag, audit_lag


# ------------------------------------ hospital_timeliness_posture (incremental)
def lifetime_rate(timely_count, referral_count):
    if referral_count == 0:
        return None
    return round2(Decimal(100) * Decimal(timely_count) / Decimal(referral_count))


def partner_posture(referral_count, rate):
    if referral_count < MIN_POSTURE_SAMPLE:
        return "GOOD_STANDING"
    if rate is None:
        return "GOOD_STANDING"
    if rate >= Decimal(POSTURE_GOOD_FLOOR):
        return "GOOD_STANDING"
    if rate >= Decimal(POSTURE_WATCH_FLOOR):
        return "WATCH"
    return "PROBATION"


# --------------------------------------------------------- behavioral_risk_score
def _canonical(factors):
    """De-duplicate and walk in the canonical FACTOR_WEIGHTS key order."""
    supplied = set(factors)
    return [f for f in RISK_FACTORS if f in supplied]


def behavioral_risk_score(risk_factors, unresolved_factors, informant_reliability):
    """Returns (risk_score, risk_tier, risk_variant_applied)."""
    mult = Decimal(RELIABILITY_MULTIPLIER[informant_reliability])
    contributions = []
    for factor in _canonical(risk_factors or []):
        contributions.append(round2(Decimal(FACTOR_WEIGHTS[factor]) * mult))
    variant = "INTERVIEW_BASED"
    if informant_reliability == "MEDICAL_RECORD_ONLY":
        variant = "RECORDS_ONLY"
        for factor in _canonical(unresolved_factors or []):
            contributions.append(
                round2(Decimal(FACTOR_WEIGHTS[factor]) * Decimal(IMPUTATION_FRACTION) * mult)
            )
    # PINNED ORDER: round each contribution to 2dp, THEN sum.
    raw = sum(contributions, Decimal("0"))
    score = round2(min(raw, Decimal(SCORE_CAP)))
    tier = "INCREASED_RISK" if score >= Decimal(RISK_TIER_THRESHOLD) else "STANDARD"
    return score, tier, variant


# ----------------------------------------------------------- donor_viability_index
def viability_index_snapshot(observation):
    ratio = observation["pao2_fio2_ratio"]
    if ratio >= 300:
        oxy = 40
    elif ratio >= 200:
        oxy = 30
    elif ratio >= 100:
        oxy = 15
    else:
        oxy = 0

    mapv = observation["map_mmhg"]
    if mapv >= 70:
        hemo_base = 35
    elif mapv >= 60:
        hemo_base = 25
    elif mapv >= 50:
        hemo_base = 10
    else:
        hemo_base = 0
    penalty = min(PRESSOR_PENALTY_CAP, PRESSOR_PENALTY_PER_AGENT * observation["pressor_count"])
    hemo = max(0, hemo_base - penalty)

    sodium = observation["sodium"]
    sodium_pts = 15 if 135 <= sodium <= 155 else 5
    urine = observation["urine_output_ml_per_kg_hr"]
    if urine >= 1.0:
        urine_pts = 10
    elif urine >= 0.5:
        urine_pts = 5
    else:
        urine_pts = 0
    metab = sodium_pts + urine_pts

    snapshot = min(100, max(0, oxy + hemo + metab))
    if observation["cardiac_arrest"]:
        snapshot = 0
    return snapshot


def dmg_bundle_met(observation):
    return (
        observation["map_mmhg"] >= 60
        and observation["pao2_fio2_ratio"] >= 300
        and 135 <= observation["sodium"] <= 155
        and observation["urine_output_ml_per_kg_hr"] >= 0.5
        and observation["pressor_count"] <= 1
    )


def physiologic_status_from(latest):
    if latest["cardiac_arrest"]:
        return "LOST"
    index = latest["viability_index_snapshot"]
    if index >= OPTIMIZED_FLOOR:
        return "OPTIMIZED"
    if index >= DECOMPENSATING_CEILING:
        return "STABILIZING"
    return "DECOMPENSATING"


# -------------------------------------------------------- cold_ischemic_projection
def cold_ischemic_projection(cross_clamp_at, depart_at, arrive_at, cit_limit_minutes):
    """Single-pass projection; the prep tier is never re-selected."""
    elapsed = floor_minutes(depart_at, cross_clamp_at)
    transit = floor_minutes(arrive_at, depart_at)
    provisional = cit_limit_minutes - elapsed - transit - BASE_PREP_MINUTES
    if provisional >= STANDARD_TIER_FLOOR:
        prep = STANDARD_PREP_MINUTES
    elif provisional >= EXPEDITED_TIER_FLOOR:
        prep = EXPEDITED_PREP_MINUTES
    else:
        prep = CRASH_PREP_MINUTES
    projected = elapsed + transit + prep
    margin = cit_limit_minutes - projected
    return transit, prep, projected, margin
