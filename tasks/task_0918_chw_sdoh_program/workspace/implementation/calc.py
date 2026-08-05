"""Calculation rules (PRD §3.2, §3.3, §3.4, §3.6, §3.7, §3.8, §3.9, §3.10)."""

from decimal import Decimal

import store
from clockutil import rhu
from errors import (
    ERR_ELIGIBILITY_CATEGORICAL_EXCLUSION,
    ERR_ELIGIBILITY_GEOGRAPHY,
    ERR_ELIGIBILITY_HOUSEHOLD_SIZE,
    ERR_ELIGIBILITY_INCOME,
    ERR_ELIGIBILITY_PROGRAM_ENROLLMENT,
)

# --- screening / risk ---
SCREENING_DOMAIN_SCORE_MIN = 0
SCREENING_DOMAIN_SCORE_MAX = 4
SCREENING_WEIGHT_SUM_REQUIRED = 100
RISK_TIER_MODERATE_MIN = Decimal("25")
RISK_TIER_HIGH_MIN = Decimal("50")
RISK_TIER_CRITICAL_MIN = Decimal("75")
SCREENING_COVERAGE_WINDOW_DAYS = 365
DEFAULT_RESCREEN_CADENCE_DAYS = 90
SDOH_DOMAINS = ("FOOD", "HOUSING", "TRANSPORT", "EMPLOYMENT", "HEALTH_LITERACY")

# --- referral / closed loop ---
ACK_SLA_HOURS = {"ROUTINE": 72, "URGENT": 24, "EMERGENT": 4}
MAX_REROUTE_COUNT = 2
REFERRAL_HOLD_EXPIRY_HOURS = 168
UNFULFILLED_REFERRAL_ESCALATION_THRESHOLD = 2

# --- home visit ---
VISIT_MIN_DURATION_MINUTES = 15
VISIT_MAX_DURATION_MINUTES = 240
ATTESTATION_WINDOW_HOURS = 72
AMENDMENT_WINDOW_DAYS = 30

# --- encounter / time tracking ---
MINUTE_ROUNDING_INCREMENT = 6
ENCOUNTER_MAX_TOTAL_MINUTES = 480
CM_CODE_MINUTE_THRESHOLD = 60
CM_EXTENDED_MINUTE_THRESHOLD = 120
CM_CODE_STANDARD = "CM-60"
CM_CODE_EXTENDED = "CM-120"
MILEAGE_BAND_1_MAX_MILES = Decimal("10")
MILEAGE_BAND_2_MAX_MILES = Decimal("30")
MILEAGE_RATE_BAND_1_CENTS = Decimal("67")
MILEAGE_RATE_BAND_2_CENTS = Decimal("55")
MILEAGE_RATE_BAND_3_CENTS = Decimal("40")
TRAVEL_REIMBURSEMENT_CAP_CENTS = 5000

# --- payer claim ---
CLAIM_UNIT_MINUTES = 15
CLAIM_ALLOWED_CENTS_PER_UNIT = 2150
CLAIM_APPEAL_WINDOW_DAYS = 60

# --- grant ---
GRANT_RATE_TIER_BREAK_CENTS = 50000
GRANT_HOURLY_RATE_TIER1_CENTS = 4200
GRANT_HOURLY_RATE_TIER2_CENTS = 3800
DEFAULT_GRANT_INDIRECT_RATE_PCT = 10

# --- escalation ---
TIER_ACK_SLA_HOURS = {1: 48, 2: 24, 3: 8}
MAX_ESCALATION_TIER = 3

EVAL_RANK = {
    "INCOME_BAND": 1,
    "GEOGRAPHY": 2,
    "HOUSEHOLD_SIZE": 3,
    "PROGRAM_ENROLLMENT": 4,
    "CATEGORICAL_EXCLUSION": 5,
}


# ---------------------------------------------------------------- screening
def weighted_risk_score(domain_scores, domain_weights):
    """Weighted SDOH score to two decimal places, plus its risk band."""
    total = Decimal(0)
    for domain, weight in domain_weights.items():
        raw = Decimal(str(domain_scores.get(domain, 0)))
        total += (raw / Decimal(SCREENING_DOMAIN_SCORE_MAX)) * Decimal(str(weight))
    score = rhu(total, 2)
    if score >= RISK_TIER_CRITICAL_MIN:
        tier = "CRITICAL"
    elif score >= RISK_TIER_HIGH_MIN:
        tier = "HIGH"
    elif score >= RISK_TIER_MODERATE_MIN:
        tier = "MODERATE"
    else:
        tier = "LOW"
    return float(score), tier


# ---------------------------------------------------------------- goals
def goal_progress_pct(direction, baseline, target, current):
    baseline = Decimal(str(baseline))
    target = Decimal(str(target))
    current = Decimal(str(current))
    if direction == "INCREASE_GOOD":
        numerator = current - baseline
        denominator = target - baseline
    else:
        numerator = baseline - current
        denominator = baseline - target
    if denominator == 0:
        return 0.0
    raw = Decimal(100) * numerator / denominator
    rounded = rhu(raw, 1)
    if rounded < Decimal("0.0"):
        rounded = Decimal("0.0")
    if rounded > Decimal("100.0"):
        rounded = Decimal("100.0")
    return float(rounded)


# ---------------------------------------------------------------- mileage
def marginal_cents(miles):
    """Marginal three-band mileage reimbursement, rounded then capped."""
    miles = Decimal(str(miles))
    if miles < 0:
        miles = Decimal(0)
    band1 = min(miles, MILEAGE_BAND_1_MAX_MILES)
    band2 = min(max(miles - MILEAGE_BAND_1_MAX_MILES, Decimal(0)),
                MILEAGE_BAND_2_MAX_MILES - MILEAGE_BAND_1_MAX_MILES)
    band3 = max(miles - MILEAGE_BAND_2_MAX_MILES, Decimal(0))
    gross = (band1 * MILEAGE_RATE_BAND_1_CENTS
             + band2 * MILEAGE_RATE_BAND_2_CENTS
             + band3 * MILEAGE_RATE_BAND_3_CENTS)
    cents = int(rhu(gross, 0))
    return min(cents, TRAVEL_REIMBURSEMENT_CAP_CENTS)


# ---------------------------------------------------------------- encounters
def encounter_billable_minutes(raw_billable):
    """Round the raw billable figure to the nearest 6-minute increment, half up."""
    quotient = rhu(Decimal(raw_billable) / Decimal(MINUTE_ROUNDING_INCREMENT), 0)
    return int(quotient) * MINUTE_ROUNDING_INCREMENT


# ---------------------------------------------------------------- payer claim
def monthly_rollup(encounters):
    """Round per encounter, then sum the already-rounded values."""
    claimed_minutes = 0
    for encounter in encounters:
        claimed_minutes += encounter_billable_minutes(encounter["raw_billable_minutes"])
    return claimed_minutes, len(encounters)


def billing_code_for(claimed_minutes):
    if claimed_minutes >= CM_EXTENDED_MINUTE_THRESHOLD:
        return CM_CODE_EXTENDED
    if claimed_minutes >= CM_CODE_MINUTE_THRESHOLD:
        return CM_CODE_STANDARD
    return None


def claim_money(claimed_minutes):
    units = claimed_minutes // CLAIM_UNIT_MINUTES
    return units, units * CLAIM_ALLOWED_CENTS_PER_UNIT


# ---------------------------------------------------------------- grant line
def grant_line_amounts(charged_minutes, committed_cents, indirect_rate_pct):
    """Tier from committed_cents BEFORE this line posts; round twice, independently."""
    if committed_cents < GRANT_RATE_TIER_BREAK_CENTS:
        hourly_rate_cents = GRANT_HOURLY_RATE_TIER1_CENTS
    else:
        hourly_rate_cents = GRANT_HOURLY_RATE_TIER2_CENTS
    direct = int(rhu(Decimal(charged_minutes) * Decimal(hourly_rate_cents) / Decimal(60), 0))
    indirect = int(rhu(Decimal(direct) * Decimal(str(indirect_rate_pct)) / Decimal(100), 0))
    return hourly_rate_cents, direct, indirect, direct + indirect


# ---------------------------------------------------------------- eligibility
def ordered_criteria(offering_id):
    rows = [c for c in store.all_rows("criterion") if c.get("offering_id") == offering_id]
    return sorted(rows, key=lambda c: (c.get("evaluation_rank", 0),
                                       c.get("created_at"),
                                       c.get("_seq", 0)))


def run_gauntlet(patient, offering_id):
    """Evaluate every criterion in rank order; stop at the first failure.

    Returns (ordered_criteria, failing_criterion_or_None, error_id_or_None).
    """
    order = ordered_criteria(offering_id)
    for criterion in order:
        kind = criterion.get("criterion_type")
        if kind == "INCOME_BAND":
            ceiling = criterion.get("max_monthly_income_cents")
            if ceiling is not None and patient.get("monthly_income_cents", 0) > ceiling:
                return order, criterion, ERR_ELIGIBILITY_INCOME
        elif kind == "GEOGRAPHY":
            allowed = criterion.get("allowed_zips") or []
            if patient.get("residence_zip") not in allowed:
                return order, criterion, ERR_ELIGIBILITY_GEOGRAPHY
        elif kind == "HOUSEHOLD_SIZE":
            size = patient.get("household_size", 0)
            low = criterion.get("min_household_size")
            high = criterion.get("max_household_size")
            if (low is not None and size < low) or (high is not None and size > high):
                return order, criterion, ERR_ELIGIBILITY_HOUSEHOLD_SIZE
        elif kind == "PROGRAM_ENROLLMENT":
            required = criterion.get("required_program_code")
            if required is not None and required not in (patient.get("program_enrollments") or []):
                return order, criterion, ERR_ELIGIBILITY_PROGRAM_ENROLLMENT
        elif kind == "CATEGORICAL_EXCLUSION":
            flag = criterion.get("excluded_flag_code")
            if flag is not None and flag in (patient.get("categorical_exclusions") or []):
                return order, criterion, ERR_ELIGIBILITY_CATEGORICAL_EXCLUSION
    return order, None, None


# ---------------------------------------------------------------- report
def pct(numerator, denominator):
    if not denominator:
        return 0.0
    return float(rhu(Decimal(100) * Decimal(numerator) / Decimal(denominator), 1))
