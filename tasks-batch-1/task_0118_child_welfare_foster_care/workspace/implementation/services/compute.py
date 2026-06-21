"""Calculations and computed-field derivation (PRD §2.7, §3.x; SCAFFOLD §1.3).

All scores are integers. The sole non-integer computed quantity is CasePlan
compliance_pct (2 dp, round-half-up). Computed fields are derived ON READ and,
where the PRD says so, persisted on explicit recompute endpoints.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db

# === Constants (verbatim from SCAFFOLD §1.3) ===============================

SCREEN_IN_THRESHOLD = 45
P1_BAND = 75
MALTREATMENT_WEIGHT = {
    "SEXUAL_ABUSE": 50,
    "PHYSICAL_ABUSE": 40,
    "NEGLECT": 25,
    "EMOTIONAL_ABUSE": 20,
}
FACTOR_WEIGHT = {
    "PRIOR_REPORT": 10,
    "CAREGIVER_SUBSTANCE": 12,
    "INJURY_VISIBLE": 15,
    "AGE_UNDER_3": 18,
    "NO_CAREGIVER": 30,
}
REPORTER_BONUS = {"MANDATED": 8, "RELATIVE": 4, "SELF": 2, "ANONYMOUS": 0}

UNSAFE_THRESHOLD = 40
REMOVAL_THRESHOLD = 70
PC_MULTIPLIER = 6
DANGER_WEIGHT = {
    "NO_FOOD": 25,
    "VIOLENCE_PRESENT": 35,
    "SUPERVISION_ABSENT": 30,
    "MEDICAL_NEGLECT": 28,
    "DRUG_ENV": 22,
    "UNSAFE_SLEEP": 18,
}

AGE_FIT_PER_YEAR = 4
AGE_FIT_CAP = 40
MALT_FIT_ACCEPT = 30
CAP_FIT_BEDS = 3
CAP_FIT_PER_BED = 10

TPR_TRIGGER_MONTHS = 15
ASFA_WINDOW_MONTHS = 22

TRIAL_VISIT_COMPLIANCE = 80
PLAN_COMPLETE_COMPLIANCE = 100

# Other constants referenced throughout the PRD.
LICENSE_TERM_DAYS = 365
PROVISIONAL_TERM_DAYS = 90
AGING_OUT_AGE = 18
APPLA_MIN_AGE = 16
HEARING_BUFFER_MINUTES = 30


# === (1) Intake screening score (PRD §3.1) =================================

def intake_screening_score(referral):
    base = MALTREATMENT_WEIGHT[referral["alleged_maltreatment"]]
    # distinct factors only — count each once
    factor_sum = sum(FACTOR_WEIGHT[f] for f in set(referral.get("priority_factors") or []))
    reporter_bonus = REPORTER_BONUS[referral["reporter_type"]]
    raw = base + factor_sum + reporter_bonus
    score = min(100, raw)  # ceiling clamp AFTER summation
    if score >= P1_BAND:
        priority = "P1_24H"
    elif score >= SCREEN_IN_THRESHOLD:
        priority = "P2_72H"
    else:
        priority = "P3_10D"
    return score, priority


# === (2) Safety assessment score (PRD §3.2) ================================

def safety_assessment_score(safety_factors, protective_capacity):
    factors = set(safety_factors or [])
    danger = sum(DANGER_WEIGHT[f] for f in factors)
    # Step 2: protective credit, capped at danger.
    credit = min(danger, protective_capacity * PC_MULTIPLIER)
    net = max(0, danger - credit)
    # Step 3: present-danger override.
    if "VIOLENCE_PRESENT" in factors or "SUPERVISION_ABSENT" in factors:
        score = max(net, REMOVAL_THRESHOLD)
    else:
        score = net
    if score >= REMOVAL_THRESHOLD:
        status, removal = "UNSAFE", True
    elif score >= UNSAFE_THRESHOLD:
        status, removal = "CONDITIONALLY_SAFE", False
    else:
        status, removal = "SAFE", False
    return score, status, removal


# === (3) Placement match score (PRD §3.5) ==================================

def placement_match_score(child_age, home, case_maltreatment):
    # headroom read from PRE-placement state (before this bed is taken).
    headroom = home["bed_capacity"] - active_placement_count(home["id"])
    age_gap = home["max_age_years"] - child_age
    age_fit = max(0, min(age_gap * AGE_FIT_PER_YEAR, AGE_FIT_CAP))
    malt_fit = MALT_FIT_ACCEPT if case_maltreatment in (home.get("accepts_maltreatment") or []) else 0
    capacity_fit = min(headroom, CAP_FIT_BEDS) * CAP_FIT_PER_BED
    return age_fit + malt_fit + capacity_fit


# === (4) Permanency clock (PRD §3.6) =======================================

def completed_whole_months(start, end):
    """Count completed month anniversaries from start to end (floor), not days/30.4."""
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # If the day-of-month (and intraday time) anniversary has not yet been
    # reached this month, the latest month is not yet complete.
    if (end.day, end.hour, end.minute, end.second, end.microsecond) < \
       (start.day, start.hour, start.minute, start.second, start.microsecond):
        months -= 1
    return max(0, months)


def permanency_clock(case):
    """Return (months_in_care, tpr_clock_breached) for a case at the current clock."""
    removal = case.get("removal_date")
    if removal is None:
        return 0, False
    from helpers import parse_dt
    removal_dt = parse_dt(removal, "removal_date")
    months = completed_whole_months(removal_dt, clock.now())
    breached = months >= TPR_TRIGGER_MONTHS
    return months, breached


# === (5) Plan compliance pct (PRD §3.8, §2.7) ==============================

def plan_compliance_pct(objectives_met, objectives_total):
    if objectives_total <= 0:
        return 0.0
    raw = (Decimal(objectives_met) / Decimal(objectives_total)) * Decimal(100)
    rounded = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(rounded)


# === Computed-field helpers ================================================

def age_years(child):
    """Whole years from date_of_birth to current clock."""
    from helpers import parse_dt
    dob = parse_dt(child["date_of_birth"], "date_of_birth")
    now = clock.now()
    years = now.year - dob.year
    if (now.month, now.day, now.hour, now.minute, now.second, now.microsecond) < \
       (dob.month, dob.day, dob.hour, dob.minute, dob.second, dob.microsecond):
        years -= 1
    return max(0, years)


def active_placement_count(foster_home_id):
    """Count of this home's placements currently in ACTIVE state."""
    return sum(
        1 for p in db.placements.values()
        if p["foster_home_id"] == foster_home_id and p["status"] == "ACTIVE"
    )


def clearances_complete(foster_home_id):
    """True only when every CaregiverScreening for this home is CLEARED.

    A home with zero screenings has no cleared screenings; per PRD the flag is
    true only when EVERY screening is CLEARED. With no screenings, there is no
    screening that is PENDING or FLAGGED, so vacuously all are CLEARED -> true.
    """
    screenings = [
        s for s in db.caregiver_screenings.values()
        if s["foster_home_id"] == foster_home_id
    ]
    return all(s["status"] == "CLEARED" for s in screenings)
