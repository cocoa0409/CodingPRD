"""Numeric constants and pinned instants stated by the PRD."""

# The logical clock reads this instant before any client sets it.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
# 2026-08-03 is a Monday; minute-of-day 540 sits inside a [480, 960) block.
MONDAY_0900 = "2026-08-03T09:00:00Z"
MONDAY_0930 = "2026-08-03T09:30:00Z"

THRESHOLDS = {
    "FTE_MINUTES_PER_WEEK": 2100,
    "TRAVEL_BUFFER_MINUTES": 20,
    "POSTURE_FULL_MAX_RATIO": 750.00,
    "POSTURE_LIMITED_MAX_RATIO": 1500.00,
    "RISK_TIER_ELEVATED_MIN": 25,
    "RISK_TIER_CRITICAL_MIN": 60,
    "RISK_SCORE_CAP": 100,
    "TRIAGE_RISK_UPLIFT_CAP": 25,
    "TRIAGE_EMS_REVIEW_MIN": 85,
    "STOCK_STUDENTS_PER_UNIT": 25,
    "DAYS_OF_SUPPLY_READY_MIN": 30.00,
    "REOPEN_WINDOW_MINUTES": 120,
    "MAX_REOPENS": 1,
    "VOID_WINDOW_MINUTES": 1440,
    "MAX_REVISION_ROUNDS": 2,
    "MAX_SCREENING_CYCLES": 3,
    "PLAN_REVIEW_DAYS": 365,
    "RESCREEN_DAYS": 14,
    "REFERRAL_DAYS": 30,
    "DISCLOSURE_CONSENT_DAYS": 30,
    "OBSERVED_WINDOW_DAYS": 90,
}

CREDENTIAL_WEIGHTS = {
    "RN": 1.00,
    "LPN": 0.60,
    "HEALTH_AIDE_DELEGATED": 0.30,
    "HEALTH_AIDE_UNDELEGATED": 0.00,
}

AVG_DAILY_UNITS = {
    "EPINEPHRINE": 0.30,
    "ALBUTEROL": 1.20,
    "INSULIN": 3.00,
    "METHYLPHENIDATE": 1.00,
    "ACETAMINOPHEN": 2.50,
}

# Standing protocol dose for an undesignated emergency administration.
STOCK_PROTOCOL_DOSE = {"EPINEPHRINE": 0.3, "ALBUTEROL": 2}

# Screening classification edges, inclusive on the named edge.
SCREENING_THRESHOLDS = {
    "VISION": {"pass_max": 30, "refer_min": 40},
    "HEARING": {"pass_max": 20, "refer_min": 30},
    "SCOLIOSIS": {"pass_max": 5, "refer_min": 7},
}

TEST_DEFAULTS = {
    "NURSE_MINUTES": 2400,
    "COT_CAPACITY": 2,
    "BLOCK_START_MINUTE": 480,
    "BLOCK_END_MINUTE": 960,
    "COVERAGE_EFFECTIVE_FROM": "2026-07-01T00:00:00Z",
    "LOT_EXPIRATION": "2027-06-30T00:00:00Z",
    "ORDER_VALID_FROM": "2026-07-01T00:00:00Z",
    "ORDER_VALID_UNTIL": "2027-06-30T00:00:00Z",
}
