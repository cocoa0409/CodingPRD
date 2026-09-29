"""
Domain constants for the Lender Appraisal Review Desk API.

Every value here is transcribed from the PRD contract under test. Tests import
these names instead of repeating magic numbers so that a threshold appearing in
several places is asserted against one single source.
"""

API_PREFIX = "/appraisal-desk"

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Completeness score (PRD 3.4)
# ---------------------------------------------------------------------------
REQUIRED_SECTIONS = [
    "SUBJECT",
    "CONTRACT",
    "NEIGHBORHOOD",
    "SITE",
    "IMPROVEMENTS",
    "SALES_COMPARISON",
    "RECONCILIATION",
    "CERTIFICATION",
]
OPTIONAL_SECTIONS = ["ADDENDA", "MARKET_CONDITIONS"]
REQUIRED_SECTION_COUNT = 8
MIN_CLOSED_COMPS = 3
MIN_EXHIBITS = 7
W_SECTION = 0.50
W_COMP = 0.30
W_EXHIBIT = 0.20
COMPLETENESS_PASS_BPS = 8500
COMPLETENESS_FAIL_BPS = 6000

# ---------------------------------------------------------------------------
# Comparable adjustment magnitudes (PRD 3.3 / 3.4)
# ---------------------------------------------------------------------------
MAX_SINGLE_GROSS_BPS = 2500
GROSS_WARN_BPS = 1500
MAX_NET_BPS = 1500
NET_WARN_BPS = 1000
MAX_GRID_COMPS = 6

# ---------------------------------------------------------------------------
# Reconciliation (PRD 3.4)
# ---------------------------------------------------------------------------
VARIANCE_FAIL_BPS = 500
VARIANCE_WARN_BPS = 250

# ---------------------------------------------------------------------------
# Rule-check battery (PRD 3.4)
# ---------------------------------------------------------------------------
RULE_CHECK_COUNT = 8
RULE_CHECK_SEQUENCE = [
    "CHK_COMPLETENESS",
    "CHK_COMP_COUNT",
    "CHK_COMP_DISTANCE",
    "CHK_COMP_AGE",
    "CHK_GROSS_ADJUSTMENT",
    "CHK_NET_ADJUSTMENT",
    "CHK_VALUE_RECONCILIATION",
    "CHK_FORM_TYPE",
]
MAX_COMP_AGE_DAYS = 365
MAX_COMP_DISTANCE_MILES = {"URBAN": 1.00, "SUBURBAN": 3.00, "RURAL": 5.00}

# ---------------------------------------------------------------------------
# Desk review quality score (PRD 3.6)
# ---------------------------------------------------------------------------
P_RULE_FAIL = 600
P_RULE_WARN = 200
P_COMP_DISTANCE = 300
P_BIAS_INDICATED = 1500
P_BIAS_SUBSTANTIATED = 3000

# ---------------------------------------------------------------------------
# Escalation requirement matrix (PRD 3.6)
# ---------------------------------------------------------------------------
HIGH_SECOND_APPRAISAL_BPS = 7000
HIGH_FIELD_REVIEW_BPS = 8500
ELEVATED_SECOND_APPRAISAL_BPS = 6000
ELEVATED_FIELD_REVIEW_BPS = 8000
STANDARD_FIELD_REVIEW_BPS = 6000
LOW_FIELD_REVIEW_BPS = 5000

# ---------------------------------------------------------------------------
# Escalation cost allocation (PRD 3.7)
# ---------------------------------------------------------------------------
FIELD_REVIEW_BASE_CENTS = 45000
SECOND_APPRAISAL_BASE_CENTS = 65000
RUSH_PCT = 0.30
RUSH_WINDOW_HOURS = 72
TIER1_FLOOR_CENTS = 50000
TIER2_CEIL_CENTS = 80000
FIELD_REVIEW_TAT_HOURS = 72
SECOND_APPRAISAL_TAT_HOURS = 168
TRAVEL_BUFFER_MINUTES = 90

# ---------------------------------------------------------------------------
# Bias risk index (PRD 3.5)
# ---------------------------------------------------------------------------
PROHIBITED_TERMS = [
    "desirable neighborhood",
    "pride of ownership",
    "crime-ridden",
    "ethnic",
    "student neighborhood",
    "up and coming",
    "gentrifying",
    "family-oriented",
]
NARRATIVE_TERM_WEIGHT = 12
COMP_SKEW_DIVISOR = 200
COMP_SKEW_FLAG_BPS = 5000
BIAS_INDICATED_THRESHOLD = 25

# ---------------------------------------------------------------------------
# LTV and decision impact (PRD 3.9)
# ---------------------------------------------------------------------------
LTV_NO_IMPACT_BPS = 8000
LTV_PRICING_BPS = 9500
LTV_CONDITION_BPS = 9700

# ---------------------------------------------------------------------------
# Appraiser performance score (PRD 3.9)
# ---------------------------------------------------------------------------
REVISION_WEIGHT = 0.60
P_BIAS_SUBSTANTIATED_APPRAISER = 1200
P_SLA_MISS = 400
PROBATION_THRESHOLD_BPS = 7000
SUSPENSION_THRESHOLD_BPS = 5500
REMOVAL_THRESHOLD_BPS = 4000
ROLLING_WINDOW_DAYS = 365
SCORE_SEED_BPS = 10000

# ---------------------------------------------------------------------------
# Reconsideration of value (PRD 3.8)
# ---------------------------------------------------------------------------
MIN_ADMISSIBLE_EVIDENCE = 2
MAX_ROV_ROUNDS = 2
ROV_APPRAISER_RESPONSE_HOURS = 120
ROV_REVISION_CAP_BPS = 2000

# ---------------------------------------------------------------------------
# AMC configuration defaults (PRD 3.2)
# ---------------------------------------------------------------------------
DEFAULT_SLA_RESPONSE_HOURS = 72
DEFAULT_DISPUTE_CAPACITY = 2
DEFAULT_ESCALATION_BUDGET_CENTS = 500000
