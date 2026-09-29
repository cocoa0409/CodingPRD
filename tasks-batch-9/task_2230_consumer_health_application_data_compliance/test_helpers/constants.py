"""Numeric thresholds, enum vocabularies, and clock anchors used by the tests."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Health-data classification
# ---------------------------------------------------------------------------
MAX_INFERENCE_DEPTH = 5
DIRECT_HEALTH_SIGNALS = (
    "DIAGNOSIS",
    "TREATMENT",
    "MEASUREMENT",
    "REPRODUCTIVE",
    "BIOMETRIC",
)

# ---------------------------------------------------------------------------
# Applicability determination
# ---------------------------------------------------------------------------
SMALL_BUSINESS_CONSUMER_MAX = 100_000
SMALL_BUSINESS_REVENUE_CENTS_MAX = 2_500_000_000
HIPAA_ONLY_RATIO = 0.95
DUAL_TRACK_RATIO = 0.5
FULL_SCOPE_RATIO = 0.5
SMALL_BUSINESS_DEADLINE = "2026-06-30"
STANDARD_DEADLINE = "2026-03-31"
MAX_ASSESSMENT_REVISIONS = 2

# ---------------------------------------------------------------------------
# Policy completeness scoring
# ---------------------------------------------------------------------------
W_CATEGORY = 0.4
W_PURPOSE = 0.35
W_THIRD_PARTY = 0.25
REQUIRED_CATEGORY_COUNT = 6
POLICY_PUBLISH_THRESHOLD = 90.0

# ---------------------------------------------------------------------------
# Residual risk scoring
# ---------------------------------------------------------------------------
WEIGHT_ADMIN = 0.3
WEIGHT_TECHNICAL = 0.35
WEIGHT_PHYSICAL = 0.1
WEIGHT_VENDOR = 0.25
GAP_PENALTY_PER_GAP = 0.035
MAX_PENALTY_MULTIPLIER = 2.0
TIER_MODERATE_MIN = 20
TIER_HIGH_MIN = 40
TIER_CRITICAL_MIN = 60

# ---------------------------------------------------------------------------
# Breach notification
# ---------------------------------------------------------------------------
HEALTH_RULE_DAYS = 60
GENERAL_RULE_DAYS = 30
MEDIA_NOTICE_THRESHOLD = 500
PER_CONSUMER_EXPOSURE_CENTS = 1200

# ---------------------------------------------------------------------------
# Consumer rights requests
# ---------------------------------------------------------------------------
RESPONSE_BASE_DAYS = 45
RESPONSE_EXTENSION_DAYS = 45
DELETE_FULFILLMENT_DAYS = 30
CONFIRM_MAX_DAYS = 30
VERIFICATION_WINDOW_DAYS = 10
MAX_VERIFICATION_ROUNDS = 3

# ---------------------------------------------------------------------------
# Deletion task fan-out
# ---------------------------------------------------------------------------
MAX_FLOW_DOWN_HOPS = 3
MAX_TASK_ATTEMPTS = 2

# ---------------------------------------------------------------------------
# Consent posture
# ---------------------------------------------------------------------------
PROCESSING_HALT_DAYS = 15

# ---------------------------------------------------------------------------
# Geofencing
# ---------------------------------------------------------------------------
GEOFENCE_LAW_BY_STATE = {
    "WA": "PROHIBITED_ALL",
    "NV": "PROHIBITED_ALL",
    "CT": "PROHIBITED_SENSITIVE_ONLY",
    "CA": "PROHIBITED_SENSITIVE_ONLY",
    "TX": "PERMITTED",
}
SENSITIVE_STANDOFF_METERS = 500
ZONE_COOLDOWN_HOURS = 24
MIN_RADIUS_METERS = 1
MAX_RADIUS_METERS = 5000

# ---------------------------------------------------------------------------
# Vendor agreements
# ---------------------------------------------------------------------------
DEFAULT_DELETION_SLA_DAYS = 30
MIN_DELETION_SLA_DAYS = 1
MAX_DELETION_SLA_DAYS = 90

# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------
STATE_CODES = ("WA", "NV", "CT", "CA", "TX")
APPLICABILITY_STATUSES = ("UNDETERMINED", "HIPAA_ONLY", "DUAL_TRACK", "CHD_REGULATED")
REGULATED_SCOPES = ("NONE", "PARTIAL", "FULL")
POLICY_COMPLIANCE_STATES = ("NO_POLICY", "CURRENT", "LAPSED")
SECURITY_PROGRAM_STATES = ("NONE", "CURRENT", "STALE")
ENTITY_STATUS_CLAIMS = ("COVERED_ENTITY", "BUSINESS_ASSOCIATE", "NOT_COVERED")
ASSESSMENT_STATES = ("DRAFT", "SUBMITTED", "APPROVED", "RETURNED", "SUPERSEDED")
SOURCE_KINDS = ("USER_PROVIDED", "DEVICE_SENSOR", "THIRD_PARTY", "DERIVED_INFERENCE")
HEALTH_SIGNAL_KINDS = (
    "DIAGNOSIS",
    "TREATMENT",
    "MEASUREMENT",
    "REPRODUCTIVE",
    "PRECISE_LOCATION",
    "BIOMETRIC",
    "NON_HEALTH",
)
CHD_CLASSIFICATIONS = ("CHD", "CHD_BY_INFERENCE", "NON_CHD")
ELEMENT_STATUSES = ("ACTIVE", "RETIRED")
PURPOSE_KINDS = ("PRIMARY_SERVICE", "ANALYTICS", "ADVERTISING", "RESEARCH", "SALE")
ACTIVITY_KINDS = ("COLLECT", "SHARE", "SELL")
DISCLOSURE_SPECIFICITIES = ("ELEMENT_NAMED", "CATEGORY_NAMED")
MAPPING_STATUSES = ("PROPOSED", "ACTIVE", "SUSPENDED", "RETIRED")
AGE_BANDS = ("ADULT", "MINOR_13_16", "UNDER_13")
CONSENT_AXIS_STATES = ("NOT_REQUESTED", "GRANTED", "WITHDRAWN")
SALE_AXIS_STATES = ("NOT_REQUESTED", "AUTHORIZED", "REVOKED")
RECORD_STATES = ("ACTIVE", "SUPERSEDED")
SPECIFICITY_MODES = ("ELEMENT_LEVEL", "CATEGORY_LEVEL")
POLICY_STATES = (
    "DRAFT",
    "IN_REVIEW",
    "PUBLISHED",
    "SUPERSEDED_PENDING_UPDATE",
    "SUPERSEDED",
)
REQUEST_KINDS = ("ACCESS", "DELETE", "CONFIRM")
SUBMITTED_CHANNELS = ("IN_APP", "EMAIL", "WEB_FORM")
REQUEST_STATES = (
    "RECEIVED",
    "VERIFICATION_PENDING",
    "VERIFIED",
    "FULFILLED",
    "DENIED",
)
TASK_STATES = ("PENDING", "NOTIFIED", "CONFIRMED", "FAILED")
VENDOR_KINDS = ("PROCESSOR", "THIRD_PARTY_RECIPIENT", "PURCHASER")
AGREEMENT_STATES = ("DRAFT", "EXECUTED", "TERMINATED")
AGREEMENT_COMPLIANCES = ("COMPLIANT", "DEFICIENT")
FACILITY_KINDS = ("SENSITIVE_HEALTH", "GENERAL_HEALTH", "NON_HEALTH")
PROHIBITION_RULES = ("PROHIBITED_ALL", "PROHIBITED_SENSITIVE_ONLY", "PERMITTED")
CAMPAIGN_STATES = ("PLANNED", "ACTIVE", "PAUSED", "ENDED")
BREACH_SCOPES = ("CHD_ONLY", "GENERAL_PII_ONLY", "MIXED")
PROTECTION_STATES = ("UNPROTECTED", "ENCRYPTED_SECURED")
BREACH_STATES = ("DISCOVERED", "REPORTABLE", "NOT_REPORTABLE", "NOTIFIED")
RISK_TIERS = ("LOW", "MODERATE", "HIGH", "CRITICAL")
SRA_STATES = ("DRAFT", "FINALIZED")

# ---------------------------------------------------------------------------
# System-supplied suspension / failure reasons
# ---------------------------------------------------------------------------
REASON_SOURCE_ELEMENT_RETIRED = "SOURCE_ELEMENT_RETIRED"
REASON_VENDOR_AGREEMENT_TERMINATED = "VENDOR_AGREEMENT_TERMINATED"
REASON_POLICY_LAPSED = "POLICY_LAPSED"
REASON_REQUEST_DENIED = "REQUEST_DENIED"
