"""Domain constants for the Surplus Lines Placement Tax API.

Every value here is transcribed from the PRD. Nothing is invented.
"""

# ---------------------------------------------------------------------------
# Roles (PRD 2.1 -- "There are exactly five roles, and their spellings are
# normative")
# ---------------------------------------------------------------------------
ROLE_PLACEMENT_BROKER = "PlacementBroker"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_TAX_FILER = "TaxFiler"
ROLE_STATE_REGULATOR = "StateRegulator"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = [
    ROLE_PLACEMENT_BROKER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_TAX_FILER,
    ROLE_STATE_REGULATOR,
    ROLE_PLATFORM_ADMIN,
]

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Diligent search (PRD 3.4)
# ---------------------------------------------------------------------------
DILIGENT_SEARCH_LOOKBACK_DAYS = 90

# ---------------------------------------------------------------------------
# Market security score (PRD 3.2)
# ---------------------------------------------------------------------------
RATING_POINTS = {
    "A_PLUS_PLUS": 40,
    "A_PLUS": 35,
    "A": 30,
    "A_MINUS": 25,
    "B_PLUS_PLUS": 15,
    "B_PLUS": 10,
    "NR": 0,
}

CAPITAL_TIER_1_CENTS = 5_000_000_000
CAPITAL_TIER_1_POINTS = 40
CAPITAL_TIER_2_CENTS = 1_500_000_000
CAPITAL_TIER_2_POINTS = 30
CAPITAL_TIER_3_CENTS = 500_000_000
CAPITAL_TIER_3_POINTS = 20
CAPITAL_TIER_FLOOR_POINTS = 5

TRUST_POINTS = 15
ALIEN_TRUST_MIN_CENTS = 540_000_000
LISTING_POINTS = 5

DRIFT_MULTIPLIER = 2
APPROVE_MIN_SCORE = 70
CONDITION_MIN_SCORE = 50

# ---------------------------------------------------------------------------
# Cancellation arithmetic (PRD 3.8)
# ---------------------------------------------------------------------------
SHORT_RATE_FACTOR = 0.90

# ---------------------------------------------------------------------------
# Filing batch penalty (PRD 3.9)
# ---------------------------------------------------------------------------
LATE_PENALTY_RATE = 0.10
LATE_PENALTY_MIN_CENTS = 2500

# ---------------------------------------------------------------------------
# Enumerations transcribed from the PRD
# ---------------------------------------------------------------------------
BROKER_STATUSES = ["ACTIVE", "SUSPENDED"]
LICENSE_TYPES = ["SURPLUS_LINES", "RESIDENT_PRODUCER"]
LICENSE_STATUSES = ["ACTIVE", "LAPSED"]

ALLOCATION_METHODS = ["HOME_STATE_SINGLE", "ALLOCATED_MULTI"]
FILING_FREQUENCIES = ["MONTHLY", "QUARTERLY"]

DOMICILE_TYPES = ["US_STATE", "ALIEN"]
AM_BEST_RATINGS = ["A_PLUS_PLUS", "A_PLUS", "A", "A_MINUS", "B_PLUS_PLUS", "B_PLUS", "NR"]
SECURITY_STATUSES = ["UNREVIEWED", "APPROVED", "CONDITIONAL", "DECLINED"]

LISTING_STATUSES = ["WHITE_LISTED", "REMOVED"]

REVIEW_STATUSES = ["DRAFT", "UNDER_REVIEW", "APPROVED", "CONDITIONAL", "DECLINED"]
REVIEW_VARIANTS = ["INITIAL_REVIEW", "RECERTIFICATION"]
REVIEW_DECISIONS = ["APPROVE", "CONDITION", "DECLINE"]

PLACEMENT_STATUSES = [
    "DRAFT",
    "SEARCH_IN_PROGRESS",
    "SEARCH_COMPLETE",
    "CHANGES_REQUESTED",
    "BOUND",
]
COVERAGE_CLASSES = [
    "PROPERTY",
    "GENERAL_LIABILITY",
    "PROFESSIONAL_LIABILITY",
    "EXCESS_CASUALTY",
    "INLAND_MARINE",
]

DECLINATION_STATUSES = ["RECORDED", "INVALIDATED"]
DECLINATION_REASON_CODES = [
    "NO_APPETITE",
    "CAPACITY",
    "UNDERWRITING",
    "RATE",
    "NOT_LICENSED_FOR_CLASS",
]

POLICY_STATUSES = ["ISSUED", "CANCELLED"]
POLICY_COMPLIANCE_STATUSES = ["PENDING_NOTICES", "NOTICES_AFFIXED", "COMPLIANT", "DEFICIENT"]
POLICY_TAX_STATUSES = ["UNCALCULATED", "CALCULATED", "ADJUSTED", "FILED", "REMITTED"]
POLICY_STAMPING_STATUSES = ["NOT_REQUIRED", "PENDING", "SUBMITTED", "ACCEPTED", "REJECTED"]

ENDORSEMENT_TYPES = [
    "PREMIUM_INCREASE",
    "PREMIUM_DECREASE",
    "EXPOSURE_CHANGE",
    "ADMINISTRATIVE",
]
ENDORSEMENT_STATUSES = ["DRAFT", "ISSUED", "VOIDED"]

CANCELLATION_TYPES = ["FLAT", "PRO_RATA", "SHORT_RATE"]
CANCELLATION_STATUSES = ["REQUESTED", "PROCESSED"]

TAX_FILING_LINE_TYPES = ["NEW_BUSINESS", "ENDORSEMENT", "CANCELLATION_RETURN"]
TAX_FILING_LINE_STATUSES = ["OPEN", "BATCHED", "FILED", "REMITTED", "VOIDED"]

FILING_BATCH_STATUSES = ["OPEN", "PREPARED", "SUBMITTED", "REMITTED"]

AFFIDAVIT_TYPES = ["DILIGENT_SEARCH", "PREMIUM_TAX"]
AFFIDAVIT_STATUSES = ["DRAFT", "SIGNED"]

STAMPING_DECISIONS = ["ACCEPT", "REJECT"]
