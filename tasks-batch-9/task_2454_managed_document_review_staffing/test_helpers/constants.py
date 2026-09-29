"""Domain constants for the managed document review staffing API.

Every value here is restated from the PRD so tests never hard-code a magic
number inline.
"""

from decimal import Decimal

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
# The startup default is exactly 2026-08-01T00:00:00Z.
CLOCK_START_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ---------------------------------------------------------------------------
# Pricing and rate constants
# ---------------------------------------------------------------------------
COMPLEXITY_TIER_MULTIPLIER = {
    "SIMPLE": Decimal("1.00"),
    "STANDARD": Decimal("1.15"),
    "COMPLEX": Decimal("1.35"),
}
LANGUAGE_PREMIUM_PER_LANGUAGE = Decimal("0.05")
PASS_TYPE_MULTIPLIER = {
    "FIRST_PASS": Decimal("1.00"),
    "SECOND_LEVEL": Decimal("0.60"),
}
HOURLY_INCREMENT_MINUTES = 6

# ---------------------------------------------------------------------------
# Invoice waterfall
# ---------------------------------------------------------------------------
QC_SURCHARGE_FACTOR = Decimal("0.20")
VOLUME_DISCOUNT_BAND_LOW_CEILING = 100000
VOLUME_DISCOUNT_BAND_MID_CEILING = 249999
VOLUME_DISCOUNT_BAND_HIGH_FLOOR = 250000
VOLUME_DISCOUNT_PCT_LOW = Decimal("0.00")
VOLUME_DISCOUNT_PCT_MID = Decimal("0.03")
VOLUME_DISCOUNT_PCT_HIGH = Decimal("0.06")

# ---------------------------------------------------------------------------
# Quality control
# ---------------------------------------------------------------------------
QC_MIN_SAMPLE_DOCS = 10
PRIVILEGE_VALIDATION_FLOOR = 2

# ---------------------------------------------------------------------------
# Reviewer scorecard and removal
# ---------------------------------------------------------------------------
REMOVAL_STRIKE_THRESHOLD = 3
ACCURACY_FLOOR_FOR_REMOVAL = Decimal("0.9000")
ACCURACY_FLOOR_MIN_SAMPLED_DOCS = 50
CLEAN_SAMPLE_CREDIT = -1
STRIKE_DELTA_BY_EVENT_TYPE = {
    "PACE_SHORTFALL": 1,
    "ACCURACY_MISS": 1,
    "PRIVILEGE_MISS": 1,
    "QC_FAILURE": 1,
    "CLEARED_STRIKE": -1,
    "REMOVAL": 0,
}

# ---------------------------------------------------------------------------
# Auto-assignment selector weights
# ---------------------------------------------------------------------------
ACCURACY_WEIGHT = Decimal("0.45")
PACE_WEIGHT = Decimal("0.30")
LANGUAGE_WEIGHT = Decimal("0.15")
SUBJECT_WEIGHT = Decimal("0.10")
STRIKE_PENALTY_WEIGHT = Decimal("0.05")
STRIKE_PENALTY_CAP = 2
PACE_NORMALISATION_CAP = Decimal("1.5")

# ---------------------------------------------------------------------------
# Staffing
# ---------------------------------------------------------------------------
MIN_EFFECTIVE_REVIEWERS = 1
DEFAULT_MIN_STAFFED_REVIEWERS = 2
DEFAULT_ONSITE_SEAT_COUNT = 1
DEFAULT_REMOTE_WORK_PERMITTED = False
DEFAULT_MAX_CONCURRENT_BATCHES = 2
DEFAULT_REMOTE_WORK_AUTHORIZED = False
DEFAULT_SECOND_LEVEL_REQUIRED = True

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
MATTER_STATUSES = [
    "INTAKE",
    "PROTOCOL_PENDING",
    "STAFFING",
    "IN_REVIEW",
    "QC_CLOSEOUT",
    "CLOSED",
    "SUSPENDED",
]
PROTOCOL_STATUSES = ["DRAFT", "CLIENT_REVIEW", "APPROVED", "SUPERSEDED"]
CREDENTIAL_STATUSES = ["UNVERIFIED", "VERIFIED", "LAPSED"]
ENGAGEMENT_STATUSES = ["SOURCED", "CLEARED", "ENGAGED", "REMOVED"]
SCREENING_STATUSES = ["PENDING", "CLEARED", "WAIVER_REQUIRED", "BLOCKED"]
AGREEMENT_STATUSES = ["PENDING", "EXECUTED", "EXPIRED", "REVOKED"]
SESSION_STATUSES = ["SCHEDULED", "ACTIVE", "CLOSED", "REVOKED"]
BATCH_STATUSES = [
    "CREATED",
    "ASSIGNED",
    "IN_PROGRESS",
    "SECOND_LEVEL",
    "QC_SAMPLING",
    "QC_PASSED",
    "QC_FAILED",
    "RELEASED",
    "DISSOLVED",
]
ASSIGNMENT_STATUSES = [
    "ASSIGNED",
    "IN_PROGRESS",
    "SUBMITTED",
    "REOPENED",
    "COMPLETED",
    "VOIDED",
]
QC_SAMPLE_OUTCOMES = ["PENDING", "PASSED", "FAILED"]
PRIVILEGE_ENTRY_STATUSES = ["DRAFT", "CHALLENGED", "VALIDATED", "FINAL"]

COMPLEXITY_TIERS = ["SIMPLE", "STANDARD", "COMPLEX"]
PRICING_MODELS = ["PER_DOCUMENT", "HOURLY"]
REVIEWER_TIERS = ["FIRST_PASS", "SECOND_LEVEL"]
PASS_TYPES = ["FIRST_PASS", "SECOND_LEVEL"]
WORKSTATION_CLASSES = ["ONSITE_SECURE", "REMOTE_VDI"]
LEDGER_ENTRY_TYPES = [
    "COMMITMENT",
    "REVERSAL",
    "ACTUAL_PER_DOCUMENT",
    "ACTUAL_HOURLY",
]
SCORECARD_EVENT_TYPES = [
    "PACE_SHORTFALL",
    "ACCURACY_MISS",
    "PRIVILEGE_MISS",
    "QC_FAILURE",
    "CLEARED_STRIKE",
    "REMOVAL",
]
PROJECTION_BASES = ["REMAINING_WORK_BASIS", "LEDGER_REPLAY_BASIS"]
ACCURACY_WEIGHTINGS = ["SAMPLE_WEIGHTED", "ASSIGNMENT_MEAN"]
PRIVILEGE_BASES = ["ATTORNEY_CLIENT", "WORK_PRODUCT", "COMMON_INTEREST"]
PRIVILEGE_DISPOSITIONS = ["WITHHELD", "REDACTED"]

# Matter statuses for which the forward-looking basis is the status default.
REMAINING_WORK_DEFAULT_STATUSES = [
    "INTAKE",
    "PROTOCOL_PENDING",
    "STAFFING",
    "IN_REVIEW",
]
# Matter statuses for which the backward-looking basis is the status default.
LEDGER_REPLAY_DEFAULT_STATUSES = ["QC_CLOSEOUT", "CLOSED", "SUSPENDED"]

# ---------------------------------------------------------------------------
# Bogus identifiers used for not-found probing
# ---------------------------------------------------------------------------
BOGUS_UUID_1 = "99999999-9999-4999-8999-999999999999"
BOGUS_UUID_2 = "88888888-8888-4888-8888-888888888888"
BOGUS_UUID_3 = "77777777-7777-4777-8777-777777777777"
BOGUS_UUID_4 = "66666666-6666-4666-8666-666666666666"
INJECTED_UUID = "11111111-1111-4111-8111-111111111111"
