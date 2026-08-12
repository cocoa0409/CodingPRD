"""Declared constants, enum member sets and the subscription tier table.

Every value here traces to PRD sections 2.1-2.12 and 3.1-3.9 (and the mirror in
SCAFFOLD.yaml global_constants).
"""

# ---------------------------------------------------------------- roles / auth
ROLES = (
    "Anonymous",
    "Homeowner",
    "HouseholdMember",
    "Appraiser",
    "InsuranceAgent",
    "ClaimsAdjuster",
    "EstateExecutor",
    "PlatformAdmin",
)

# Roles whose X-User-ID names a persisted row (PRD 2.1).
ENTITY_BACKED_MEMBER_ROLES = ("Homeowner", "HouseholdMember", "EstateExecutor")
ENTITY_BACKED_APPRAISER_ROLE = "Appraiser"

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# ------------------------------------------------------------ logical clock
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# --------------------------------------------------------------- time windows
BILLING_PERIOD_DAYS = 30
TRIAL_DAYS = 14
PAST_DUE_GRACE_DAYS = 10
REFRESH_INTERVAL_DAYS = 365
REFRESH_DUE_BAND_DAYS = 15
REFRESH_GRACE_DAYS = 30
APPRAISAL_VALIDITY_DAYS = 1095
APPRAISAL_BUFFER_HOURS = 24
SHARE_MAX_DURATION_DAYS = 90
PACKAGE_VALIDITY_DAYS = 180

# ------------------------------------------------------------------ thresholds
APPRAISAL_REQUIRED_THRESHOLD_CENTS = 1000000
SCHEDULE_REQUIRED_THRESHOLD_CENTS = 500000
MAX_APPEALS_PER_LINE = 2
SHARE_DEFAULT_ACCESS_CAP = 10
MAX_ITEM_QUANTITY = 999
MIN_ITEM_QUANTITY = 1
MIN_ALLOCATION_QUANTITY = 1
MONTH_DAYS_FOR_AGE = 30

FAIR_DIVISION_TOLERANCE_PCT = 5.0
SELL_DISPOSITION_COST_PCT = 12.0
DONATE_DISPOSITION_COST_PCT = 0.0
DISCARD_DISPOSITION_COST_PCT = 0.0
KEEP_DISPOSITION_COST_PCT = 0.0

# ------------------------------------------------------------- evidence ladder
EVIDENCE_TIERS = ("NONE", "PHOTO_ONLY", "PHOTO_SERIAL", "DOCUMENTED")
EVIDENCE_RANK = {"NONE": 0, "PHOTO_ONLY": 1, "PHOTO_SERIAL": 2, "DOCUMENTED": 3}
CLAIM_MIN_EVIDENCE_TIER = "PHOTO_SERIAL"
PACKAGE_MIN_EVIDENCE_TIER = "PHOTO_ONLY"
CLAIM_MIN_EVIDENCE_TIER_RANK = EVIDENCE_RANK[CLAIM_MIN_EVIDENCE_TIER]
PACKAGE_MIN_EVIDENCE_TIER_RANK = EVIDENCE_RANK[PACKAGE_MIN_EVIDENCE_TIER]

# ------------------------------------------------------------------ enum sets
MEMBER_ROLES = ("OWNER", "LIMITED", "EXECUTOR", "HEIR")
SUBSCRIPTION_TIER_NAMES = ("BASIC", "PLUS", "ESTATE")
SUBSCRIPTION_STATUSES = ("TRIAL", "ACTIVE", "PAST_DUE", "LAPSED", "CLOSED")
REFRESH_STATES = ("CURRENT", "DUE", "GRACE", "OVERDUE")
WRITE_GATE_STATES = ("OPEN", "RESTRICTED", "READ_ONLY")
ITEM_CATEGORIES = (
    "JEWELRY",
    "FINE_ART",
    "ELECTRONICS",
    "FURNITURE",
    "APPLIANCE",
    "COLLECTIBLE",
    "MUSICAL_INSTRUMENT",
    "FIREARM",
    "WATCH",
    "GENERAL",
)
APPRAISAL_SCOPES = (
    "JEWELRY",
    "FINE_ART",
    "ELECTRONICS",
    "COLLECTIBLE",
    "MUSICAL_INSTRUMENT",
    "FIREARM",
    "WATCH",
    "GENERAL",
)
ASSET_KINDS = ("PHOTO", "SERIAL_PLATE", "RECEIPT", "PROVENANCE_DOC", "APPRAISAL_PDF")
ASSET_STATUSES = ("STORED", "DELETED")
ITEM_LIFECYCLE_STATES = ("DRAFT", "CATALOGED", "FROZEN", "REPLACED", "DISPOSED")
VALUATION_STATES = ("UNVALUED", "DECLARED_ONLY", "APPRAISAL_REQUIRED", "CERTIFIED")
EFFECTIVE_VALUE_BASES = ("NONE", "DECLARED", "ACV", "APPRAISAL")
COVERAGE_MODES = ("BLANKET", "SCHEDULED")
APPRAISER_STATUSES = ("ACTIVE", "SUSPENDED")
APPRAISAL_STATUSES = ("REQUESTED", "CERTIFIED", "VOIDED", "EXPIRED")
VOID_REASONS = ("APPRAISER_WITHDRAWN", "SCOPE_REVOKED", "VALUE_DISPUTED")
PACKAGE_STATUSES = ("DRAFT", "GENERATED", "DELIVERED", "SUPERSEDED", "EXPIRED")
PERILS = ("FIRE", "THEFT", "WATER", "STORM", "OTHER")
SETTLEMENT_BASES = ("ACV", "RCV")
DEDUCTIBLE_MODES = ("PRO_RATA", "HIGHEST_VALUE_FIRST")
CLAIM_STATUSES = (
    "OPEN",
    "SUBMITTED",
    "UNDER_REVIEW",
    "SUPPLEMENT_REQUESTED",
    "SETTLED",
    "DENIED",
    "WITHDRAWN",
)
CLAIM_LINE_STATUSES = ("PENDING", "APPROVED", "DENIED", "APPEALED")
DENIAL_REASONS = ("EVIDENCE_INSUFFICIENT", "NOT_COVERED", "VALUE_DISPUTED", "DUPLICATE")
ESTATE_PLAN_STATUSES = ("DRAFT", "PROPOSED", "APPROVED", "EXECUTED")
VALUATION_MODES = ("GROSS", "NET")
DISPOSITIONS = ("KEEP", "SELL", "DONATE", "DISCARD")
SCOPE_KINDS = ("HOUSEHOLD", "ROOM", "PACKAGE", "CLAIM")
REDACTION_LEVELS = ("VALUES_HIDDEN", "SERIALS_HIDDEN", "FULL")
SHARE_STATUSES = ("ACTIVE", "REVOKED", "EXPIRED", "EXHAUSTED", "VOIDED_BY_SCOPE")
VOIDED_REASONS = ("SCOPE_DELETED", "SCOPE_SUPERSEDED", "SUBSCRIPTION_LAPSED")
BILLING_OUTCOMES = ("PAYMENT_SUCCEEDED", "PAYMENT_FAILED", "LAPSE", "CLOSE")
ADJUDICATION_DECISIONS = ("APPROVE", "DENY")
PRORATION_MODES = ("DAILY", "WHOLE_PERIOD")
COVERAGE_GAP_BASES = ("SCHEDULED_FIRST", "BLANKET_FIRST")

# ------------------------------------------------------- freezing claim states
FREEZING_CLAIM_STATES = ("OPEN", "SUBMITTED", "UNDER_REVIEW", "SUPPLEMENT_REQUESTED")
LIVE_PLAN_STATES = ("DRAFT", "PROPOSED", "APPROVED")
COUNTED_ITEM_STATES = ("DRAFT", "CATALOGED", "FROZEN")
VALUED_ITEM_STATES = ("CATALOGED", "FROZEN")

# ------------------------------------------------------------------ tier table
SUBSCRIPTION_TIERS = {
    "BASIC": {
        "monthly_fee_cents": 900,
        "max_items": 50,
        "max_assets": 200,
        "max_asset_bytes": 2000000000,
        "max_households": 1,
        "included_appraisal_credits": 0,
        "included_packages_per_period": 1,
        "tier_rank": 1,
    },
    "PLUS": {
        "monthly_fee_cents": 2900,
        "max_items": 500,
        "max_assets": 2000,
        "max_asset_bytes": 20000000000,
        "max_households": 2,
        "included_appraisal_credits": 2,
        "included_packages_per_period": 4,
        "tier_rank": 2,
    },
    "ESTATE": {
        "monthly_fee_cents": 7900,
        "max_items": 5000,
        "max_assets": 20000,
        "max_asset_bytes": 200000000000,
        "max_households": 5,
        "included_appraisal_credits": 6,
        "included_packages_per_period": 12,
        "tier_rank": 3,
    },
}

# ------------------------------------------------------------------ pagination
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0

# --------------------------------------------------------------- gate lists
# PRD 2.7 Gate 1 - endpoints still callable while the household is READ_ONLY.
WRITE_GATE_EXCLUSION_LIST = frozenset(
    {
        ("POST", "/vault/subscriptions/{subscription_id}/billing-event"),
        ("POST", "/vault/subscriptions/{subscription_id}/reinstate"),
        ("POST", "/vault/subscriptions/{subscription_id}/attest-refresh"),
        ("POST", "/vault/claims"),
        ("POST", "/vault/claims/{claim_id}/lines"),
        ("POST", "/vault/claims/{claim_id}/submit"),
        ("POST", "/vault/claims/{claim_id}/withdraw"),
        ("POST", "/vault/claim-lines/{claim_line_id}/adjudicate"),
        ("POST", "/vault/claim-lines/{claim_line_id}/appeal"),
        ("POST", "/vault/claims/{claim_id}/settle"),
        ("POST", "/vault/share-grants/{share_grant_id}/revoke"),
    }
)

# PRD 2.7 Gate 2 - endpoints blocked while the household is RESTRICTED.
RESTRICTED_GATE_BLOCK_LIST = frozenset(
    {
        ("POST", "/vault/packages/{package_id}/generate"),
        ("POST", "/vault/share-grants"),
    }
)
