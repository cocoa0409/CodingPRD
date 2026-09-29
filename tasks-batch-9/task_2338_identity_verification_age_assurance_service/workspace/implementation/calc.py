"""Every calculation of the scaffold, expressed in integer / basis-point arithmetic.

PRD 2.5: there are no decimal quantities in this API. Ratios that are *reported* round
half up; scores that are *spent* truncate toward zero; exactly one quantity (the age
buffer) rounds up.
"""
from decimal import ROUND_HALF_UP, Decimal

# --- session_expiry_schedule -------------------------------------------------
SESSION_TTL_MINUTES = 60

# --- review_sla_schedule ----------------------------------------------------
REVIEW_SLA_HOURS = 48

# --- session_risk_assessment ------------------------------------------------
TIER_BASE = {"BASIC": 10, "STANDARD": 30, "ENHANCED": 60}
VALUE_BUMP_LOW_MAX_CENTS = 24999
VALUE_BUMP_MID_MAX_CENTS = 999999
VALUE_BUMP_MID = 10
VALUE_BUMP_HIGH = 20
JURISDICTION_MISMATCH_BUMP = 20
NO_STANDARD_DOCS_BUMP = 10
PRIOR_REJECT_BUMP = 15
PRIOR_REJECT_BUMP_CAP = 30
RISK_HIGH_MIN = 70
RISK_MEDIUM_MIN = 40

# --- document_authenticity_assessment ---------------------------------------
TAMPER_UNIT_BPS = 450
TIER_CLEAN_MIN_BPS = 9000
TIER_MID_MIN_BPS = 7000
TIER_MULTIPLIER_CLEAN_BPS = 10000
TIER_MULTIPLIER_MID_BPS = 15000
TIER_MULTIPLIER_WEAK_BPS = 20000
MRZ_INVALID_CAP_BPS = 4000
SUSPECT_FLOOR_BPS = 5000

# --- liveness_pad_decision --------------------------------------------------
RISK_PAD_BUMP = {"LOW": 0, "MEDIUM": 300, "HIGH": 800}
PAD_RETRY_BUMP_BPS = 200
ACTIVE_MODALITY_RELIEF_BPS = 250
PAD_CEILING_BPS = 9500
INCONCLUSIVE_BAND_BPS = 300

# --- method_evidence_quality ------------------------------------------------
BIO_MATCH_WEIGHT_BPS = 6000
BIO_PAD_WEIGHT_BPS = 4000
INCONCLUSIVE_HALVING_DIVISOR = 2
VOUCHING_QUALITY_BPS = 9000
ATTESTATION_QUALITY_BPS = 7000

# --- assurance_score --------------------------------------------------------
SCORE_CAP = 100
RESTRICTED_MULTIPLIER_BPS = 5000
ATTESTATION_CEILING = 70

# --- age_assurance_decision -------------------------------------------------
U13_MAX_MONTHS = 155
B13_15_MAX_MONTHS = 191
B16_17_MAX_MONTHS = 215
B18_20_MAX_MONTHS = 251
MONTHS_PER_YEAR = 12
AGE_BANDS = ("U13", "B13_15", "B16_17", "B18_20", "A21_PLUS")
MINOR_BANDS = ("U13", "B13_15", "B16_17")

# --- cohort_disparity_evaluation --------------------------------------------
MIN_COHORT_SAMPLE = 50
MIN_COHORT_COUNT = 3
DISPARITY_RESTRICT_BPS = 12500
DISPARITY_MONITOR_BPS = 11000

# --- retention_schedule -----------------------------------------------------
RETENTION_DAYS = 90

# --- review_credit_pool -----------------------------------------------------
CREDITS_PER_ASSIGNMENT = 1

# --- client_rolling_window_usage --------------------------------------------
QUOTA_WINDOW_HOURS = 24


def round_half_up_div(numerator, denominator):
    """round_half_up(numerator / denominator) with a value at the midpoint going away from zero."""
    if denominator == 0:
        return 0
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_div(numerator, denominator):
    """Truncation toward zero."""
    if denominator == 0:
        return 0
    quotient = Decimal(numerator) / Decimal(denominator)
    return int(quotient.to_integral_value(rounding="ROUND_DOWN"))


def ceil_div(numerator, denominator):
    if denominator == 0:
        return 0
    return -((-numerator) // denominator)


# --- session_risk_assessment ------------------------------------------------

def session_risk(tier, value_cents, subject_jurisdiction, home_jurisdiction,
                 documentation_status, prior_rejected_count):
    if value_cents <= VALUE_BUMP_LOW_MAX_CENTS:
        value_bump = 0
    elif value_cents <= VALUE_BUMP_MID_MAX_CENTS:
        value_bump = VALUE_BUMP_MID
    else:
        value_bump = VALUE_BUMP_HIGH
    mismatch_bump = JURISDICTION_MISMATCH_BUMP if subject_jurisdiction != home_jurisdiction else 0
    docs_bump = NO_STANDARD_DOCS_BUMP if documentation_status == "NO_STANDARD_DOCS" else 0
    history_bump = min(PRIOR_REJECT_BUMP_CAP, PRIOR_REJECT_BUMP * prior_rejected_count)
    score = TIER_BASE[tier] + value_bump + mismatch_bump + docs_bump + history_bump
    if score >= RISK_HIGH_MIN:
        level = "HIGH"
    elif score >= RISK_MEDIUM_MIN:
        level = "MEDIUM"
    else:
        level = "LOW"
    return score, level


# --- document_authenticity_assessment ---------------------------------------

def document_authenticity(passed_feature_count, required_feature_count, tamper_signal_count,
                          mrz_checksum_valid, authenticity_floor_bps):
    base = round_half_up_div(10000 * passed_feature_count, required_feature_count)
    if base >= TIER_CLEAN_MIN_BPS:
        multiplier = TIER_MULTIPLIER_CLEAN_BPS
    elif base >= TIER_MID_MIN_BPS:
        multiplier = TIER_MULTIPLIER_MID_BPS
    else:
        multiplier = TIER_MULTIPLIER_WEAK_BPS
    penalty = floor_div(TAMPER_UNIT_BPS * tamper_signal_count * multiplier, 10000)
    raw = max(0, base - penalty)
    score = min(raw, MRZ_INVALID_CAP_BPS) if not mrz_checksum_valid else raw
    if score >= authenticity_floor_bps:
        assessment = "AUTHENTIC"
    elif score >= SUSPECT_FLOOR_BPS:
        assessment = "SUSPECT"
    else:
        assessment = "FORGED"
    return {
        "base_score_bps": base,
        "tamper_tier_multiplier_bps": multiplier,
        "tamper_penalty_bps": penalty,
        "authenticity_score_bps": score,
        "assessment": assessment,
    }


# --- liveness_pad_decision --------------------------------------------------

def liveness_decision(pad_threshold_bps, risk_level, retry_index, capture_modality, pad_score_bps):
    relief = ACTIVE_MODALITY_RELIEF_BPS if capture_modality == "ACTIVE" else 0
    unclamped = (pad_threshold_bps + RISK_PAD_BUMP[risk_level]
                 + PAD_RETRY_BUMP_BPS * retry_index - relief)
    threshold = min(PAD_CEILING_BPS, max(0, unclamped))
    if pad_score_bps >= threshold:
        decision = "PASS"
    elif pad_score_bps >= threshold - INCONCLUSIVE_BAND_BPS:
        decision = "INCONCLUSIVE"
    else:
        decision = "FAIL"
    return threshold, decision


# --- method_evidence_quality ------------------------------------------------

def biometric_quality(match_score_bps, pad_score_bps, decision):
    blended = floor_div(BIO_MATCH_WEIGHT_BPS * match_score_bps + BIO_PAD_WEIGHT_BPS * pad_score_bps, 10000)
    if decision == "PASS":
        return blended
    if decision == "INCONCLUSIVE":
        return floor_div(blended, INCONCLUSIVE_HALVING_DIVISOR)
    return 0


def count_quality(numerator_count, denominator_count):
    return floor_div(10000 * numerator_count, denominator_count)


def contribution_points(assurance_weight, evidence_quality_bps):
    return floor_div(assurance_weight * evidence_quality_bps, 10000)


# --- age_assurance_decision -------------------------------------------------

def age_buffer_months(mae_months, multiplier_bps):
    return ceil_div(mae_months * multiplier_bps, 10000)


def resolve_band(effective_age_months):
    if effective_age_months <= U13_MAX_MONTHS:
        return "U13"
    if effective_age_months <= B13_15_MAX_MONTHS:
        return "B13_15"
    if effective_age_months <= B16_17_MAX_MONTHS:
        return "B16_17"
    if effective_age_months <= B18_20_MAX_MONTHS:
        return "B18_20"
    return "A21_PLUS"


def complete_months_between(dob_year, dob_month, dob_day, now_dt):
    months = (now_dt.year - dob_year) * 12 + (now_dt.month - dob_month)
    if now_dt.day < dob_day:
        months -= 1
    return max(0, months)


# --- cohort_disparity_evaluation --------------------------------------------

def cohort_rate(count, attempt_count):
    if attempt_count == 0:
        return 0
    return round_half_up_div(10000 * count, attempt_count)
