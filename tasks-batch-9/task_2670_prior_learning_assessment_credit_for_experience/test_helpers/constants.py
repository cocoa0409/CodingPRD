"""Numeric constants pinned verbatim by the PRD.

Every value below is quoted from a rule-bearing sentence of the PRD so that a
test never re-derives a magic number inline.
"""

# --------------------------------------------------------------------------
# Basis points (PRD S2.6)
# --------------------------------------------------------------------------
BP_SCALE = 10000

# --------------------------------------------------------------------------
# Coverage (PRD S3.4)
# --------------------------------------------------------------------------
PRIMARY_CREDIT_BP = 10000
SUPPORTING_CREDIT_BP = 5000
MIN_PROVISIONAL_COVERAGE_BP = 5000
DEFAULT_MASTERY_THRESHOLD_BP = 7000
OUTCOME_WEIGHT_TOTAL_BP = 10000

# --------------------------------------------------------------------------
# Rubric scoring (PRD S3.7)
# --------------------------------------------------------------------------
RUBRIC_POINTS_POSSIBLE = 4
RUBRIC_RATIO_BY_POINTS = {0: 0, 1: 2500, 2: 5000, 3: 7500, 4: 10000}
DEFAULT_PASS_THRESHOLD_BP = 7000

# --------------------------------------------------------------------------
# Turnaround allowance (PRD S3.6)
# --------------------------------------------------------------------------
SOURCE_BASE_HOURS = {
    "CREDIT_BY_EXAM": 72,
    "PORTFOLIO": 240,
    "MILITARY_TRAINING": 96,
    "INDUSTRY_CREDENTIAL": 96,
}
ARTIFACT_TIER_MULTIPLIER_BP_LOW = 10000     # 3 artifacts or fewer, or no portfolio
ARTIFACT_TIER_MULTIPLIER_BP_MID = 12500     # 4 through 8 artifacts
ARTIFACT_TIER_MULTIPLIER_BP_HIGH = 15000    # 9 or more artifacts
EXPEDITED_MULTIPLIER_BP = 5000
AT_RISK_OFFSET_BP = 8000
BREACH_ELAPSED_BP = 10000
AT_RISK_ELAPSED_BP = 8000
CAPACITY_BUFFER_HOURS = 24

# --------------------------------------------------------------------------
# Fee pricing (PRD S3.10)
# --------------------------------------------------------------------------
BASE_ASSESSMENT_FEE_CENTS = {
    "CREDIT_BY_EXAM": 5000,
    "PORTFOLIO": 15000,
    "MILITARY_TRAINING": 0,
    "INDUSTRY_CREDENTIAL": 7500,
}
PER_CREDIT_FEE_CENTS = 2500
ARTIFACT_SURCHARGE_LOW_CENTS = 0        # 3 artifacts or fewer
ARTIFACT_SURCHARGE_MID_CENTS = 4000     # 4 through 8
ARTIFACT_SURCHARGE_HIGH_CENTS = 9000    # 9 or more
RUSH_SURCHARGE_BP = 2500
APPEAL_FILING_FEE_CENTS = 6000
SLA_SERVICE_CREDIT_BP = 1500

DISCOUNT_TIER_HIGH_MIN_SUBTOTAL_CENTS = 25000
DISCOUNT_TIER_HIGH_BP = 1000
DISCOUNT_TIER_MID_MIN_SUBTOTAL_CENTS = 10000
DISCOUNT_TIER_MID_BP = 500
DISCOUNT_TIER_NONE_BP = 0

# --------------------------------------------------------------------------
# Settlement on exit (PRD S3.5 / S3.10)
# --------------------------------------------------------------------------
RETENTION_BP_FROM_UNDER_ASSESSMENT = 5000
RETENTION_BP_DEFAULT = 0
REMAND_FIXED_REFUND_CENTS = 6000

# --------------------------------------------------------------------------
# Budgets and windows
# --------------------------------------------------------------------------
REVISION_BUDGET = 2               # PRD S3.5: "The revision budget is two"
APPEAL_BUDGET = 1                 # PRD S3.9: "A denied student has one appeal"
APPEAL_WINDOW_HOURS = 336         # PRD S3.8: clock advanced by 336 hours

# --------------------------------------------------------------------------
# Programme configuration bounds (PRD S3.1)
# --------------------------------------------------------------------------
MIN_TOTAL_CREDITS_REQUIRED = 30
MIN_COURSE_CREDITS = 1
MAX_COURSE_CREDITS = 12
MIN_CREDENTIAL_RANK = 1
MAX_CREDENTIAL_RANK = 3
UPPER_LEVEL_MIN_RANK = 3
LOWER_LEVEL_MIN_RANK = 2

ALL_SOURCE_TYPES = [
    "CREDIT_BY_EXAM",
    "PORTFOLIO",
    "MILITARY_TRAINING",
    "INDUSTRY_CREDENTIAL",
]
