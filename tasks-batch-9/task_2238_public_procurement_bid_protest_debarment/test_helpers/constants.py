"""Pinned numeric constants, rates, thresholds and canonical clock instants.

Every value here is copied from the PRD narrative (§2.7, §3.x) so that tests
never hard-code a magic number whose provenance is unclear.
"""

# ---------------------------------------------------------------- the clock
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ------------------------------------------------------- pagination (§2.3)
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ------------------------------------------- question period / addenda (§3.3)
QUESTION_DEADLINE_LEAD_DAYS = 7
MAX_CUMULATIVE_EXTENSION_DAYS = 21

# ----------------------------------------------------- informality loading
INFORMALITY_LOADING_RATE = 0.0025

# ------------------------------------------------- protest filing fee (§3.7)
PROTEST_FEE_BASE_CENTS = 25000

AD_VALOREM_TIER_1_CEILING_CENTS = 10_000_000
AD_VALOREM_TIER_2_CEILING_CENTS = 100_000_000
AD_VALOREM_RATE_TIER_1 = 0.00075
AD_VALOREM_RATE_TIER_2 = 0.00050
AD_VALOREM_RATE_TIER_3 = 0.00025

GROUNDS_MULTIPLIERS = {
    "SOLICITATION_IMPROPRIETY": 0.1255,
    "RESPONSIVENESS_DETERMINATION": 0.3335,
    "RESPONSIBILITY_DETERMINATION": 0.2955,
    "AWARD_IMPROPRIETY": 0.5015,
    "EVALUATION_ERROR": 0.2135,
}

# ------------------------------------------- protest timeliness windows (§3.7)
TIMELINESS_DAYS_SOLICITATION_IMPROPRIETY = -1  # effective bid due minus one day
TIMELINESS_DAYS_RESPONSIVENESS_DETERMINATION = 7
TIMELINESS_DAYS_RESPONSIBILITY_DETERMINATION = 7
TIMELINESS_DAYS_EVALUATION_ERROR = 7
TIMELINESS_DAYS_AWARD_IMPROPRIETY = 10

# ------------------------------------------------- award obligation (§3.6)
ADMIN_FEE_TIER_1_CEILING_CENTS = 100_000_000
ADMIN_FEE_TIER_2_CEILING_CENTS = 500_000_000
ADMIN_FEE_RATE_TIER_1 = 0.0150
ADMIN_FEE_RATE_TIER_2 = 0.0110
ADMIN_FEE_RATE_TIER_3 = 0.0075
PROTEST_RISK_RESERVE_RATE = 0.0050

# --------------------------------------- responsibility composite score (§3.5)
HIGH_VALUE_PROFILE_FLOOR_CENTS = 500_000_000
STANDARD_WEIGHTS = {
    "financial_capacity": 0.3,
    "past_performance": 0.4,
    "integrity": 0.3,
}
HIGH_VALUE_WEIGHTS = {
    "financial_capacity": 0.5,
    "past_performance": 0.3,
    "integrity": 0.2,
}
STRIKE_PENALTY_POINTS_PER_STRIKE = 7
STRIKE_PENALTY_CAP = 20
INTEGRITY_CEILING_TRIGGER = 40
INTEGRITY_CEILING_SCORE = 49
RESPONSIBILITY_THRESHOLD = 60.00

# -------------------------------------------- debarment severity score (§3.9)
AGGRAVATING_WEIGHTS = {
    "FRAUD": 40,
    "BID_RIGGING": 35,
    "FALSE_CERTIFICATION": 25,
    "REPEATED_NONPERFORMANCE": 20,
    "SAFETY_VIOLATION": 15,
    "ADMINISTRATIVE_DEFAULT": 5,
}
MITIGATING_WEIGHTS = {
    "SELF_DISCLOSURE": 15,
    "RESTITUTION_PAID": 12,
    "COMPLIANCE_PROGRAM": 10,
    "COOPERATION": 8,
}
MITIGATION_CREDIT_CAP_FRACTION = 0.5
PRIOR_STRIKE_ESCALATION_POINTS = 10
INTERIM_SUSPENSION_THRESHOLD = 35

DEBARMENT_PERIOD_TIERS = (
    (80, 60),
    (60, 36),
    (40, 24),
    (20, 12),
)
DEBARMENT_SEVERITY_FLOOR = 20

RESPONSE_WINDOW_DAYS = 14
REINSTATEMENT_SERVED_FRACTION = 0.5

# ---------------------------------------------------- hearing logistics (§3.8)
ROOM_CHANGEOVER_BUFFER_MINUTES = 30
OFFICER_DAILY_DOCKET_CAPACITY_MINUTES = 480
MAX_CONTINUANCES = 2

# ------------------------------------------------- subcontractor tiers (§3.9)
MAX_SUBCONTRACT_TIER = 3
