"""Literal constants the PRD pins for the mobile driver license issuance API.

Every value here is copied from the PRD narrative so the test suite never
recomputes a rule the PRD already states in words.
"""

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
# A freshly launched server reads exactly this instant, and only the clock
# endpoint moves it.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# --------------------------------------------------------------------------
# Identity proofing assurance score
# --------------------------------------------------------------------------
EVIDENCE_POINTS = {
    "DOCUMENT_SCAN": {"STRONG": 250, "FAIR": 150, "WEAK": 60},
    "BIOMETRIC_MATCH": {"STRONG": 200, "FAIR": 120, "WEAK": 40},
    "KNOWLEDGE_CHECK": {"STRONG": 90, "FAIR": 50, "WEAK": 20},
    "ADDRESS_CORROBORATION": {"STRONG": 80, "FAIR": 40, "WEAK": 10},
}
REPEAT_ATTEMPT_PENALTY = 25
IAL2_MIN_SCORE = 420
IAL1_5_MIN_SCORE = 260

MIN_EVIDENCE_ITEMS_FOR_SUBMIT = 2

# --------------------------------------------------------------------------
# Interoperability profile defaults
# --------------------------------------------------------------------------
DEFAULT_REQUIRED_ASSURANCE_LEVEL = "IAL2"
DEFAULT_MAX_DEVICES_PER_HOLDER = 2
DEFAULT_MAX_ACTIVE_CREDENTIALS_PER_HOLDER = 2
DEFAULT_PROOFING_VALIDITY_DAYS = 180
DEFAULT_REVOCATION_FRESHNESS_SECONDS = 300
DEFAULT_AGE_ONLY_ALLOWED_ELEMENTS = ["age_over_18", "age_over_21", "portrait"]

# --------------------------------------------------------------------------
# Verifier exposure index
# --------------------------------------------------------------------------
OVER_CEILING_WEIGHT = 12
EXCESS_ELEMENT_WEIGHT = 6
PSEUDONYM_REUSE_WEIGHT = 20
PSEUDONYM_REUSE_MIN = 3
ROLLING_WINDOW_DAYS = 30
INDEX_CEILING = 100
PROBATION_THRESHOLD = 60
SUSPEND_THRESHOLD = 90

# --------------------------------------------------------------------------
# Verifier invoice
# --------------------------------------------------------------------------
TIER_1_MAX_QUERIES = 100
TIER_2_MAX_QUERIES = 500
TIER_2_FACTOR = 0.80
TIER_3_FACTOR = 0.60
PROBATION_SURCHARGE_PCT = 0.15
VOLUME_DISCOUNT_MIN_QUERIES = 250
VOLUME_DISCOUNT_PCT = 0.10
DEFAULT_BASE_RATE_CENTS = 25

# --------------------------------------------------------------------------
# Credential reissuance settlement
# --------------------------------------------------------------------------
BASE_REISSUANCE_FEE_CENTS = 3000
EXPEDITE_FEE_CENTS = 1500
DEVICE_REBINDING_FEE_CENTS = 800
WAIVER_TIER_1_MIN_CENTS = 5300
WAIVER_TIER_2_MIN_CENTS = 3800
WAIVER_TIER_1_PCT = 0.20
WAIVER_TIER_2_PCT = 0.10
LOST_DEVICE_ADDITIONAL_WAIVER_PCT = 0.05

# --------------------------------------------------------------------------
# Data minimisation
# --------------------------------------------------------------------------
CORE_ELEMENTS = [
    "family_name",
    "given_name",
    "birth_date",
    "portrait",
    "document_number",
    "expiry_date",
    "issuing_authority",
    "driving_privileges",
    "address",
    "age_over_18",
    "age_over_21",
]

# --------------------------------------------------------------------------
# Delivery failure coupling
# --------------------------------------------------------------------------
FAILED_DELIVERY_STALE_THRESHOLD = 2

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
STANDARD_VERSIONS = ["ISO_18013_5_2021", "ISO_18013_5_2024", "ISO_18013_7_2024"]
ASSURANCE_LEVELS = ["IAL1", "IAL1_5", "IAL2"]
PHYSICAL_CREDENTIAL_STATUSES = [
    "VALID",
    "EXPIRED",
    "SUSPENDED",
    "REVOKED",
    "CANCELLED",
]
PROOFING_STATES = [
    "COLLECTING",
    "SUBMITTED",
    "VERIFIED",
    "RETURNED",
    "DENIED",
    "EXPIRED",
    "CONSUMED",
]
EVIDENCE_TYPES = [
    "DOCUMENT_SCAN",
    "BIOMETRIC_MATCH",
    "KNOWLEDGE_CHECK",
    "ADDRESS_CORROBORATION",
]
EVIDENCE_QUALITIES = ["STRONG", "FAIR", "WEAK"]
DEVICE_PLATFORMS = ["IOS", "ANDROID"]
PROTECTION_METHODS = ["BIOMETRIC", "PASSCODE"]
DEVICE_STATES = [
    "REGISTERED",
    "ATTESTED",
    "BOUND",
    "LOST_REPORTED",
    "WIPED",
    "RETIRED",
]
SECURE_ELEMENT_GRADES = ["HARDWARE_STRONGBOX", "HARDWARE_TEE", "SOFTWARE"]
CREDENTIAL_LIFECYCLE_STATES = [
    "PENDING_PROVISION",
    "ACTIVE",
    "SUSPENDED",
    "REPLACED",
    "REVOKED",
    "EXPIRED",
]
CREDENTIAL_SYNC_STATES = ["IN_SYNC", "UPDATE_PENDING", "UPDATE_FAILED", "STALE"]
SUSPEND_REASONS = [
    "DEVICE_LOST",
    "ADMIN_HOLD",
    "UPDATE_FAILED",
    "PHYSICAL_CREDENTIAL_SUSPENDED",
]
UPDATE_ORDER_REASONS = [
    "ADDRESS_CHANGE",
    "RENEWAL",
    "RESTRICTION_CHANGE",
    "REVOCATION",
]
UPDATE_ORDER_STATUSES = ["OPEN", "PARTIALLY_DELIVERED", "COMPLETED", "FAILED_CLOSED"]
UPDATE_DELIVERY_STATUSES = ["PENDING", "DELIVERED", "FAILED", "SUPERSEDED"]
DELIVERY_FAILURE_CODES = ["DEVICE_UNREACHABLE", "ATTESTATION_STALE", "USER_DECLINED"]
REVOCATION_STATUSES = ["SUSPENDED", "REVOKED", "REINSTATED", "EXPIRED"]
REVOCATION_REASONS = [
    "DEVICE_LOST",
    "HOLDER_REQUEST",
    "FRAUD",
    "PHYSICAL_CREDENTIAL_REVOKED",
    "RENEWAL_SUPERSEDE",
    "ADMIN_HOLD",
    "RECOVERY",
    "VALIDITY_LAPSED",
    "UPDATE_FAILED",
]
VERIFIER_CATEGORIES = [
    "COMMERCIAL",
    "LAW_ENFORCEMENT",
    "GOVERNMENT_SERVICE",
    "AGE_RESTRICTED_RETAIL",
]
TRUST_STATUSES = ["APPLIED", "APPROVED", "PROBATION", "SUSPENDED", "TERMINATED"]
READER_TRUST_STATES = ["PENDING", "LISTED", "DELISTED"]
PRESENTATION_CONTEXTS = ["ROUTINE", "AGE_ONLY", "LAW_ENFORCEMENT"]
HANDSET_HANDLING_MODES = ["NO_SURRENDER", "TAP_TO_READ", "SURRENDER_REQUESTED"]
PRESENTATION_STATES = [
    "REQUESTED",
    "CONSENT_PENDING",
    "CONSENT_GRANTED",
    "COMPLETED",
    "DENIED_BY_HOLDER",
    "BLOCKED_BY_POLICY",
    "ABORTED",
]
PRESENTATION_OUTCOMES = [
    "DISCLOSED",
    "DENIED_BY_HOLDER",
    "BLOCKED_BY_POLICY",
    "ABORTED",
]
BILLING_STATES = ["UNBILLED", "BILLED", "VOIDED"]
ABORT_REASONS = [
    "CREDENTIAL_UPDATE_PENDING",
    "CREDENTIAL_REVOKED",
    "VERIFIER_TERMINATED",
]
