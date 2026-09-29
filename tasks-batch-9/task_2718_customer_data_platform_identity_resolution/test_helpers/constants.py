"""Domain constants taken from the PRD: enumerations, weights, floors and defaults."""

# --- the logical clock ------------------------------------------------------
# The server boots with its logical clock at this instant.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --- source systems --------------------------------------------------------
CHANNEL_TYPES = ["TRANSACTIONS", "LOYALTY", "WEB", "APP", "SUPPORT"]
DQ_SCORING_MODES = ["UNWEIGHTED_MEAN", "WEIGHTED_COMPONENTS", "PENALIZED_WEIGHTED"]
SOURCE_STATUSES = ["REGISTERED", "ACTIVE", "QUARANTINED"]
DEFAULT_TRUST_TIER = 3
DEFAULT_PII_COMPLETENESS_FLOOR = 0.70
DEFAULT_DQ_SCORING_MODE = "WEIGHTED_COMPONENTS"

# --- data quality scoring --------------------------------------------------
DQ_COMPONENTS = ["email_norm", "phone_norm", "loyalty_number", "postal_code", "name_pair"]
W_EMAIL_NORM = 0.30
W_PHONE_NORM = 0.20
W_LOYALTY_NUMBER = 0.20
W_POSTAL_CODE = 0.15
W_NAME_PAIR = 0.15
DQ_COMPONENT_WEIGHTS = {
    "email_norm": W_EMAIL_NORM,
    "phone_norm": W_PHONE_NORM,
    "loyalty_number": W_LOYALTY_NUMBER,
    "postal_code": W_POSTAL_CODE,
    "name_pair": W_NAME_PAIR,
}
MALFORMED_PENALTY = 0.10
DQ_RECORD_MIN = 0.60
DQ_MIN_SAMPLE = 5
MAX_RETRY_ROUNDS = 2

# --- ingest batches --------------------------------------------------------
BATCH_STATUSES = ["RECEIVED", "VALIDATED", "QUARANTINED", "PROMOTED", "REJECTED"]
BATCH_REJECTION_REASONS = ["RETRY_LIMIT_REACHED", "SOURCE_QUARANTINED"]
MAX_BATCH_RECORDS = 200

# --- profiles ---------------------------------------------------------------
RESOLUTION_STATUSES = ["UNRESOLVED", "RESOLVED", "MERGED_AWAY"]
PRIVACY_STATUSES = ["NORMAL", "SUPPRESSED", "DELETION_PENDING", "DELETED", "LEGAL_HOLD"]
LOYALTY_TIERS = ["NONE", "SILVER", "GOLD", "PLATINUM"]

# --- households ------------------------------------------------------------
HOUSEHOLD_MAX_MEMBERS = 6
HOUSEHOLD_STATUSES = ["ACTIVE", "DISSOLVED"]

# --- match rules and identity links ----------------------------------------
RULE_KINDS = ["DETERMINISTIC", "PROBABILISTIC"]
DETERMINISTIC_KEYS = ["EMAIL_NORM", "PHONE_NORM", "LOYALTY_NUMBER"]
MISSING_IDENTIFIER_POLICIES = ["STRICT_ZERO", "RENORMALIZE"]
RULE_STATUSES = ["ENABLED", "DISABLED"]
LINK_STATUSES = ["PROPOSED", "CONFIRMED", "REJECTED", "VOIDED"]
LINK_VOID_REASONS = ["RULE_DISABLED", "PROFILE_DELETED", "SUPERSEDED"]
EVIDENCE_KEYS = [
    "email_similarity",
    "phone_similarity",
    "name_similarity",
    "address_similarity",
]
W_EMAIL_SIMILARITY = 0.40
W_PHONE_SIMILARITY = 0.25
W_NAME_SIMILARITY = 0.20
W_ADDRESS_SIMILARITY = 0.15
CONFIDENCE_WEIGHTS = {
    "email_similarity": W_EMAIL_SIMILARITY,
    "phone_similarity": W_PHONE_SIMILARITY,
    "name_similarity": W_NAME_SIMILARITY,
    "address_similarity": W_ADDRESS_SIMILARITY,
}
DEFAULT_AUTO_MERGE_THRESHOLD = 0.92
DEFAULT_REVIEW_FLOOR = 0.65
DEFAULT_MIN_PRECISION = 0.60
SYSTEM_ACTOR = "system"

# --- consent ---------------------------------------------------------------
CONSENT_CHANNELS = ["EMAIL", "SMS", "PUSH", "DIRECT_MAIL", "ADVERTISING"]
CONSENT_PURPOSES = ["MARKETING", "PERSONALIZATION", "MEASUREMENT"]
CONSENT_STATES = ["OPT_IN", "OPT_OUT"]
CONSENT_STATUSES = ["ACTIVE", "SUPERSEDED", "EXPIRED", "TOMBSTONED"]
ACTIVATION_GATING_PURPOSE = "MARKETING"

# --- suppression ------------------------------------------------------------
SUPPRESSION_TYPES = ["PRIVACY_DELETE", "DO_NOT_SELL", "LEGAL_HOLD", "GLOBAL_OPT_OUT"]
SUPPRESSION_STATUSES = ["ACTIVE", "RELEASED", "EXPIRED"]

# --- segments ---------------------------------------------------------------
SEGMENT_ATTRIBUTES = [
    "postal_code",
    "loyalty_tier",
    "lifetime_value_cents",
    "channel_engagement_score",
    "inferred_health_interest",
    "inferred_ethnicity_affinity",
    "precise_geolocation_grid",
]
SENSITIVE_SEGMENT_ATTRIBUTES = [
    "inferred_health_interest",
    "inferred_ethnicity_affinity",
    "precise_geolocation_grid",
]
SEGMENT_OPERATORS = ["EQ", "GTE", "IN"]
SEGMENT_STATUSES = [
    "DRAFT",
    "PENDING_GOVERNANCE_REVIEW",
    "APPROVED",
    "GOVERNANCE_EXPIRED",
    "RETIRED",
]
MAX_SEGMENT_CRITERIA = 6
DEFAULT_GOVERNANCE_VALID_DAYS = 90

# --- destinations and activations ------------------------------------------
PLATFORM_KINDS = ["ADVERTISING", "MESSAGING"]
HASHING_ALGORITHMS = ["SHA256_EMAIL_LOWER", "SHA256_PHONE_E164"]
MATCH_RATE_BASES = ["GROSS", "NET"]
DESTINATION_STATUSES = ["ACTIVE", "INACTIVE"]
DEFAULT_MATCH_RATE_BASIS = "GROSS"
DEFAULT_MIN_MATCH_RATE = 0.70
DEFAULT_MIN_AUDIENCE_SIZE = 50
DEFAULT_COOLDOWN_MINUTES = 60
DEFAULT_MAX_CONCURRENT_ACTIVATIONS = 2
DEFAULT_DELETION_ACK_SLA_HOURS = 72
ACTIVATION_STATUSES = [
    "DRAFT",
    "DISPATCHED",
    "ACTIVE",
    "UNDERPERFORMING",
    "PAUSED",
    "TERMINATED",
]
ACTIVATION_PAUSED_REASONS = [
    "SEGMENT_RETIRED",
    "GOVERNANCE_EXPIRED",
    "CONSENT_WITHDRAWN",
    "OPERATOR",
]
QUOTA_CONSUMING_ACTIVATION_STATUSES = ["DISPATCHED", "ACTIVE", "UNDERPERFORMING"]

# --- attribution and overlap -----------------------------------------------
ATTRIBUTION_BASES = ["TOTAL", "INCREMENTAL"]

# --- erasure ---------------------------------------------------------------
DELETION_REQUEST_ORIGINS = ["DATA_SUBJECT", "RETENTION", "REGULATOR"]
DELETION_REQUEST_STATUSES = [
    "RECEIVED",
    "BLOCKED_LEGAL_HOLD",
    "PROPAGATING",
    "PARTIALLY_VERIFIED",
    "VERIFIED",
]
VENDOR_TASK_STATUSES = ["PENDING", "DISPATCHED", "ACKNOWLEDGED", "FAILED", "TIMED_OUT"]
VENDOR_ACK_OUTCOMES = ["ACKNOWLEDGED", "FAILED"]

# --- pagination ------------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# --- precision widths ------------------------------------------------------
TWO_DP_FIELDS = [
    "dq_score",
    "pii_completeness_floor",
    "channel_engagement_score",
]
FOUR_DP_FIELDS = [
    "dq_pass_rate",
    "auto_merge_threshold",
    "review_floor",
    "min_precision",
    "precision_estimate",
    "confidence",
    "min_match_rate",
    "gross_match_rate",
    "net_match_rate",
    "effective_match_rate",
    "jaccard_index",
    "containment_in_other",
    "containment_of_other",
]
CENT_FIELDS = [
    "lifetime_value_cents",
    "combined_lifetime_value_cents",
    "revenue_cents",
    "attributed_revenue_cents",
    "revenue_per_member_cents",
]
