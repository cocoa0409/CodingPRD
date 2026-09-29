"""Numeric constants, rate tables and thresholds declared by the API contract.

Every value here is transcribed from the specification text; nothing is
inferred. Tests import these instead of repeating magic numbers so that a
single reading of the contract governs the whole suite.
"""

# ─── Logical clock ────────────────────────────────────────────────────────
# "Before any call to this endpoint the logical clock reads exactly
#  2026-08-01T00:00:00Z; it never falls back to wall-clock time."
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_MS = "2026-08-01T00:00:00.000Z"

# ─── Pagination ───────────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Appraisal scoring ────────────────────────────────────────────────────
INFORMATIONAL_WEIGHT = 3
EVIDENTIAL_WEIGHT = 3
BRAND_HERITAGE_WEIGHT = 2
UNIQUENESS_WEIGHT = 2
AGE_BONUS_YEARS_PER_POINT = 5
AGE_BONUS_MAX = 10
VOLUME_PENALTY_FREE_LINEAR_FEET = 50
VOLUME_PENALTY_FEET_PER_POINT = 10
VOLUME_PENALTY_MAX = 15
APPRAISAL_SCORE_MIN = 0
APPRAISAL_SCORE_MAX = 100
PROVENANCE_VERIFIED_MULTIPLIER = 1.00
PROVENANCE_UNVERIFIED_MULTIPLIER = 0.80
SCREENING_PROVENANCE_MULTIPLIER = 1.00

# ─── Confidentiality risk scoring ─────────────────────────────────────────
CLASS_WEIGHT = {
    "INTERNAL_BUSINESS": 10,
    "EXTERNAL_RESEARCHER": 30,
    "MEDIA": 45,
}
NDA_CREDIT = -12
SENSITIVITY_WEIGHT = {
    "PUBLIC": 0,
    "INTERNAL": 15,
    "CONFIDENTIAL": 35,
    "RESTRICTED": 60,
}
LEGAL_HOLD_SURCHARGE = 25
REDACTION_CREDIT = -10
RISK_SCORE_MIN = 0
RISK_SCORE_MAX = 100
RISK_REDACTION_THRESHOLD = 75

# ─── Access service fee ───────────────────────────────────────────────────
PAGES_PER_UNIT = 11
PER_PAGE_CENTS = {
    "INTERNAL_BUSINESS": 0,
    "EXTERNAL_RESEARCHER": 35,
    "MEDIA": 90,
}
VOLUME_TIER_BREAK_LOW = 100      # total pages <= 100 -> 0.000
VOLUME_TIER_BREAK_HIGH = 500     # 101..500 -> 0.075; >= 501 -> 0.125
VOLUME_TIER_PCT_NONE = 0.000
VOLUME_TIER_PCT_MID = 0.075
VOLUME_TIER_PCT_HIGH = 0.125
BASE_HANDLING_CENTS = 2500
MEDIA_SURCHARGE_CENTS = 15000

# ─── Migration job cost waterfall ─────────────────────────────────────────
FORMAT_RATE_CENTS = {
    "PAPER": 900,
    "PHOTO": 1800,
    "FILM": 3600,
    "MAGNETIC_TAPE": 4200,
    "BORN_DIGITAL": 600,
}
VOLUME_DISCOUNT_PCT_NONE = 0.00      # subtotal <= 50000
VOLUME_DISCOUNT_PCT_MID = 0.06       # 50001 .. 200000
VOLUME_DISCOUNT_PCT_HIGH = 0.11      # >= 200001
VOLUME_DISCOUNT_BREAK_LOW = 50000
VOLUME_DISCOUNT_BREAK_HIGH = 200000
HANDLING_FEE_CENTS_LOW = 1500        # discounted <= 25000
HANDLING_FEE_CENTS_MID = 4000        # 25001 .. 100000
HANDLING_FEE_CENTS_HIGH = 9000       # >= 100001
HANDLING_BREAK_LOW = 25000
HANDLING_BREAK_HIGH = 100000
CONDITION_SURCHARGE_PCT = {
    "GOOD": 0.00,
    "FAIR": 0.05,
    "POOR": 0.12,
    "UNSTABLE": 0.20,
}

# ─── Storage zone environmental status ────────────────────────────────────
TEMP_COMPLIANT_MAX_C = 18.0
RH_COMPLIANT_MIN_PCT = 30.0
RH_COMPLIANT_MAX_PCT = 50.0
TEMP_MARGINAL_MAX_C = 21.0
RH_MARGINAL_MIN_PCT = 30.0
RH_MARGINAL_MAX_PCT = 55.0

# ─── At-risk census ───────────────────────────────────────────────────────
AT_RISK_FORMATS = ("MAGNETIC_TAPE", "FILM")
AT_RISK_ITEM_STATUSES = ("UNPROCESSED", "ACCESSIONED", "IN_TREATMENT")

# ─── Exhibit loans ────────────────────────────────────────────────────────
LIGHT_RECOVERY_DAYS = 45
LIVE_LOAN_STATUSES = ("REQUESTED", "CONFIRMED", "OUT")
LOANABLE_CONDITION_GRADES = ("GOOD", "FAIR")

# ─── Trademark continuous-use coverage ────────────────────────────────────
MAX_ALLOWED_GAP_YEARS = 3
MIN_COVERAGE_PCT = 25.00

# ─── Field bounds ─────────────────────────────────────────────────────────
YEAR_MIN = 1800
YEAR_MAX = 2100
RETENTION_YEARS_MIN = 0
RETENTION_YEARS_MAX = 200
MAX_REQUESTED_ITEMS = 50
MAX_EVIDENCE_ITEMS = 80
MAX_OVERLAPPING_JOBS_MIN = 1
MAX_OVERLAPPING_JOBS_MAX = 20

# A syntactically valid identifier that is never assigned to any row; used to
# probe the seventeen per-resource NOT_FOUND codes.
MISSING_UUID = "00000000-0000-0000-0000-0000000000ff"
