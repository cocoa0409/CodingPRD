"""Domain constants for the Lifeline prepaid wireless eligibility and enrollment API."""

API_PREFIX = "/lifeline"

# ---------------------------------------------------------------- logical clock
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ------------------------------------------------- federal poverty guideline math
FPG_BASE_ANNUAL_CENTS = 1560000
FPG_PER_ADDITIONAL_CENTS = 552000
INCOME_MULTIPLIER_STANDARD = 1.35
INCOME_MULTIPLIER_TRIBAL = 1.50
PROGRAM_INCOME_CEILING_CENTS = 6000000
MINIMUM_THRESHOLD_CENTS = 2106000

# Pinned threshold literals: (household_size, tribal_lands_flag) -> cents
INCOME_THRESHOLD_LITERALS = {
    (1, False): 2106000,
    (2, False): 2851200,
    (3, False): 3596400,
    (4, False): 4341600,
    (4, True): 4824000,
    (1, True): 2340000,
    (8, True): 6000000,
    (9, False): 6000000,
}

# ------------------------------------------------------------ recertification
MONTHS_PER_YEAR_FACTOR = 4
RECERT_CYCLE_DAYS = 365
RECERT_NOTICE_LEAD_DAYS = 60
RECERT_RESPONSE_DAYS = 60

# ------------------------------------------------------------- eligibility
ELIGIBILITY_VALID_DAYS = 90
MAX_DOCUMENTATION_RESUBMISSIONS = 2

# ------------------------------------------------------------- support pricing
BASE_SUPPORT_CENTS_PER_MONTH = 925
TRIBAL_ENHANCEMENT_CENTS_PER_MONTH = 2500
BROADBAND_UPLIFT_CENTS_PER_MONTH = 275
MIN_SUPPORT_DAYS = 1

# The four monthly rates the two additive components produce.
RATE_NON_TRIBAL_VOICE = 925
RATE_NON_TRIBAL_BROADBAND = 1200
RATE_TRIBAL_VOICE = 3425
RATE_TRIBAL_BROADBAND = 3700

# ----------------------------------------------------------------- recoupment
PENALTY_TIER_1_CENTS = 500
PENALTY_TIER_2_CENTS = 1500
PENALTY_RATE_LOW = 0.05
PENALTY_RATE_MID = 0.10
PENALTY_RATE_HIGH = 0.20

# ----------------------------------------------------------------- risk score
RISK_WEIGHT_DUPLICATE_ADDRESS = 40
RISK_WEIGHT_NON_USAGE = 30
RISK_WEIGHT_RECERT_LAPSE = 20
RISK_WEIGHT_PER_DEVICE = 10
RISK_DEVICE_COUNT_CAP = 2
RISK_WEIGHT_TRANSFERRED = 15
RISK_SCORE_CEILING = 100

# ------------------------------------------------------------------- sampling
MIN_SAMPLE_SIZE = 1
MAX_SAMPLE_SIZE = 50

# ------------------------------------------------------------ usage and cure
NON_USAGE_WINDOW_DAYS = 30
CURE_PERIOD_DAYS = 15

# -------------------------------------------------------------- household slots
DEFAULT_MAX_BENEFIT_SLOTS = 1

# ------------------------------------------------------------------- porting
BENEFIT_PORT_FREEZE_DAYS = 60

# -------------------------------------------------------------- handset freeze
DEVICE_FREEZE_DAYS = 365
DEVICE_REISSUE_BUFFER_DAYS = 30
DEVICE_FREEZE_TOTAL_DAYS = DEVICE_FREEZE_DAYS + DEVICE_REISSUE_BUFFER_DAYS  # 395
MODEL_TIER_LADDER = ["BASIC", "STANDARD", "SMART"]

# --------------------------------------------------------------------- appeals
APPEAL_WINDOW_DAYS = 30
MAX_REVIEW_ROUNDS = 3

# ------------------------------------------------------------------ pagination
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ------------------------------------------------------------------ enum sets
PROVIDER_STATUSES = ["ACTIVE", "SUSPENDED"]
ADDRESS_STATUSES = [
    "UNVERIFIED",
    "DUPLICATE_FLAGGED",
    "RESOLVED_MULTI_HOUSEHOLD",
    "RESOLVED_SINGLE_HOUSEHOLD",
]
SUBSCRIBER_STATUSES = [
    "PROSPECT",
    "ELIGIBILITY_PENDING",
    "VERIFIED_ELIGIBLE",
    "DUPLICATE_HOLD",
    "ENROLLED",
    "DE_ENROLLED",
    "BARRED",
]
QUALIFYING_BENEFITS = [
    "NONE",
    "SNAP",
    "MEDICAID",
    "SSI",
    "FPHA",
    "VETERANS_PENSION",
    "TRIBAL_TANF",
    "BIA_GENERAL_ASSISTANCE",
]
TRIBAL_ONLY_PROGRAMS = ["TRIBAL_TANF", "BIA_GENERAL_ASSISTANCE"]
ELIGIBILITY_BASES = ["INCOME", "BENEFIT"]
ELIGIBILITY_CHECK_STATUSES = [
    "PENDING_VERIFIER",
    "DOCUMENTATION_REQUIRED",
    "ELIGIBLE_CONFIRMED",
    "INELIGIBLE",
]
VERIFIER_OUTCOMES = ["MATCH", "NO_MATCH", "DOCUMENTATION_REQUIRED"]
INCOME_VARIANTS = ["STRICT_ANNUALIZED", "NOT_APPLICABLE"]
ELIGIBILITY_BASIS_VALUES = ["NONE", "INCOME", "BENEFIT", "TRIBAL_BENEFIT"]
SERVICE_TYPES = ["VOICE", "BROADBAND", "BUNDLED"]
BENEFIT_STATUSES = ["ACTIVE", "DE_ENROLLED"]
USAGE_STATUSES = ["PENDING_FIRST_USE", "USING", "NON_USAGE_FLAGGED", "CURE_EXPIRED"]
RECERT_STATUSES = ["NOT_DUE", "NOTICED", "NON_RESPONSIVE", "RESPONDED_INELIGIBLE"]
ENROLLMENT_DEVICE_STATUSES = ["AWAITING_DEVICE", "DEVICE_ISSUED", "RECLAIM_PENDING"]
DE_ENROLLMENT_REASONS = [
    "SUBSCRIBER_REQUEST",
    "NON_USAGE",
    "RECERT_NON_RESPONSE",
    "INELIGIBLE_ON_RECERT",
    "DUPLICATE_HOUSEHOLD",
    "AUDIT_INELIGIBLE",
]
BARRING_REASONS = [
    "NON_USAGE",
    "RECERT_NON_RESPONSE",
    "INELIGIBLE_ON_RECERT",
    "AUDIT_INELIGIBLE",
]
DEVICE_STATUSES = ["IN_STOCK", "ISSUED", "RECLAIM_PENDING", "RETIRED", "LOST"]
RETURN_CONDITIONS = ["GOOD", "DAMAGED", "LOST"]
TRANSFER_STATUSES = [
    "REQUESTED",
    "ACCEPTED_COMPLETED",
    "REJECTED",
    "SUPERSEDED",
]
REJECTION_REASONS = ["CONSENT_INVALID", "TARGET_CAPACITY", "OTHER"]
CLAIM_STATUSES = [
    "DRAFT",
    "FILED",
    "HELD",
    "UNDER_AUDIT",
    "AUDIT_PASSED",
    "AUDIT_FAILED",
    "SUPERSEDED",
]
SAMPLE_STATUSES = ["DRAWN", "ADJUDICATED_PASS", "ADJUDICATED_FAIL"]
SAMPLE_FINDINGS = [
    "COMPLIANT",
    "INELIGIBLE_SUBSCRIBER",
    "DUPLICATE_HOUSEHOLD",
    "NON_USAGE_UNCURED",
    "MISSING_CERTIFICATION",
]
CASE_TYPES = ["SERVICE_COMPLAINT", "DE_ENROLLMENT_APPEAL"]
CASE_STATUSES = [
    "SUBMITTED",
    "UNDER_REVIEW",
    "REMANDED",
    "GRANTED",
    "DENIED",
    "RESOLVED",
]
CASE_DECISIONS = ["RESOLVE_WITH_CREDIT", "GRANT_REINSTATE", "DENY", "REMAND"]
