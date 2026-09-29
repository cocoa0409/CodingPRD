"""Domain thresholds and numeric constants stated by the PRD."""

# Clock -------------------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Cooling-off window ------------------------------------------------------
NON_DIRECTED_EXTRA_DAYS = 7
MIN_RE_DISCLOSURE_DAYS = 2

# Donor exclusion screening ----------------------------------------------
BMI_HARD_MAX = 35.0
BMI_SOFT_MIN = 30.0
EGFR_HARD_MIN = 80.0
EGFR_SOFT_MAX = 90.0
SYSTOLIC_HARD_MIN = 160
SYSTOLIC_SOFT_MIN = 140
HBA1C_HARD_MIN = 6.5
HBA1C_SOFT_MIN = 5.7
MIN_DONOR_AGE_YEARS = 18
SENIOR_DONOR_AGE_YEARS = 60
HARDSHIP_SOFT_MIN = 7
SUPPORT_SOFT_MAX = 3

MEDICAL_SOFT_POINTS_BMI = 2
MEDICAL_SOFT_POINTS_EGFR = 3
MEDICAL_SOFT_POINTS_SYSTOLIC = 2
MEDICAL_SOFT_POINTS_HBA1C = 2
MEDICAL_SOFT_POINTS_AGE = 1
PSYCHOSOCIAL_SOFT_POINTS_HARDSHIP = 3
PSYCHOSOCIAL_SOFT_POINTS_SUPPORT = 2

# Risk indices ------------------------------------------------------------
SCREENING_MEDICAL_WEIGHT = 0.6
SCREENING_PSYCHOSOCIAL_WEIGHT = 0.4
FINAL_MEDICAL_WEIGHT = 0.5
FINAL_PSYCHOSOCIAL_WEIGHT = 0.5
DEFERRAL_SURCHARGE = 1.5
NON_DIRECTED_SURCHARGE = 2.0
RISK_INDEX_CEILING = 8.0

# Cold ischemia -----------------------------------------------------------
CROSS_MATCH_HOLD_MINUTES = 45
MAX_CIT_MINUTES = 1080
CHAIN_CIT_BUDGET_MINUTES = 2400
OFFER_RESPONSE_WINDOW_HOURS = 6

# ABO compatibility (donor -> permitted recipients) -----------------------
ABO_COMPATIBILITY = {
    "O": ["O", "A", "B", "AB"],
    "A": ["A", "AB"],
    "B": ["B", "AB"],
    "AB": ["AB"],
}

# Waitlist ----------------------------------------------------------------
URGENCY_WEIGHT = 2.0
ACTIVE_DAY_WEIGHT = 0.007
DIALYSIS_YEAR_WEIGHT = 1.005
CPRA_TIER_HIGH_MIN = 0.98
CPRA_TIER_HIGH_POINTS = 10.0
CPRA_TIER_MID_MIN = 0.80
CPRA_TIER_MID_POINTS = 4.0
CPRA_TIER_LOW_MIN = 0.20
CPRA_TIER_LOW_POINTS = 1.0
PEDIATRIC_BONUS = 3.0
PEDIATRIC_AGE_MAX_EXCLUSIVE = 18

# Follow-up ---------------------------------------------------------------
REQUIRED_FIELDS_SIX_MONTH = 12
REQUIRED_FIELDS_ONE_YEAR = 14
REQUIRED_FIELDS_TWO_YEAR = 10
REQUIRED_FIELDS_BY_INTERVAL = {
    "SIX_MONTH": REQUIRED_FIELDS_SIX_MONTH,
    "ONE_YEAR": REQUIRED_FIELDS_ONE_YEAR,
    "TWO_YEAR": REQUIRED_FIELDS_TWO_YEAR,
}
FOLLOW_UP_DUE_OFFSET_DAYS = {"SIX_MONTH": 180, "ONE_YEAR": 365, "TWO_YEAR": 730}
DELINQUENCY_GRACE_DAYS = 30

# Outcome reviews ---------------------------------------------------------
MIN_COHORT_SIZE = 10
FLAG_THRESHOLD = 0.85
WATCH_THRESHOLD = 0.95

# Compliance posture ------------------------------------------------------
CIT_BREACH_RESTRICT_COUNT = 2

# Donor cost reimbursement ------------------------------------------------
MEDICAL_CAP_CENTS = 1000000
TRAVEL_CAP_CENTS = 350000
DONOR_LIFETIME_CAP_CENTS = 1500000
INSURANCE_PER_CLAIM_CAP_CENTS = 600000
NLDAC_PER_DONOR_CAP_CENTS = 800000

# Program defaults --------------------------------------------------------
DEFAULT_ORGAN_TYPE = "KIDNEY"
DEFAULT_COOLING_OFF_DAYS = 7
DEFAULT_COMPLETENESS_THRESHOLD_PCT = 80
DEFAULT_COMPLIANCE_THRESHOLD_PCT = 75
DEFAULT_EXPECTED_ONE_YEAR_SURVIVAL_RATE = 0.95
DEFAULT_DONOR_FUND_POOL_CENTS = 5000000
DEFAULT_LOST_WAGE_DAILY_CAP_CENTS = 30000
DEFAULT_LOST_WAGE_WEEKLY_CAP_CENTS = 150000
DEFAULT_TURNOVER_BUFFER_MINUTES = 45

# Field-name pools used to drive follow-up completeness assertions.
# Names are arbitrary labels supplied by the caller; only the count of distinct
# names that carry a non-empty value is contractually meaningful.
FOLLOW_UP_FIELD_POOL = [
    "bp_systolic",
    "bp_diastolic",
    "creatinine",
    "egfr",
    "proteinuria",
    "weight_kg",
    "smoking_status",
    "insurance_status",
    "employment_status",
    "complication_codes",
    "readmission_flag",
    "vital_status",
    "medication_list",
    "quality_of_life_score",
]


def follow_up_fields(count: int) -> list:
    """Return `count` distinct field names from the pool."""
    assert count <= len(FOLLOW_UP_FIELD_POOL), "field pool exhausted"
    return FOLLOW_UP_FIELD_POOL[:count]
