"""Business constants, enum vocabularies and canonical payloads for the ROI API."""

# ---------------------------------------------------------------- base paths
API_PREFIX = "/roi"
CLOCK_PATH = "/_clock/set_current_utc"

# The logical clock starts at this instant before any test touches it.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------- numeric constants
SECONDS_PER_DAY = 86400
MAX_TOLL_SECONDS = 864000
MILLICENTS_PER_CENT = 1000
GRACE_BUSINESS_DAYS = 2
MAX_DELIVERY_ATTEMPTS = 3
REVIEW_WINDOW_DAYS = 30
AMENDMENT_WINDOW_DAYS = 60

# ---------------------------------------------------------------- pagination
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# ---------------------------------------------------------------- enums
FULFILLMENT_STATUSES = [
    "INTAKE_REVIEW",
    "AUTH_DEFECT_PENDING",
    "COMPILATION",
    "SENSITIVE_REVIEW",
    "REDACTION",
    "RELEASE_READY",
    "RELEASED",
    "DENIED",
    "CLOSED",
    "CANCELLED",
]

BILLING_STATUSES = [
    "PENDING_INVOICE",
    "INVOICED",
    "PAID",
    "WAIVED",
    "NOT_BILLABLE",
]

RETRIEVAL_STATUSES = ["PENDING", "RETRIEVED", "UNAVAILABLE", "WITHDRAWN"]
SENSITIVITY_STATUSES = [
    "UNCLASSIFIED",
    "NOT_SENSITIVE",
    "SEGREGATED_PENDING_REVIEW",
    "AUTHORIZED_INCLUDE",
    "WITHHELD",
]
REDACTION_STATUSES = ["NOT_REQUIRED", "OPEN", "APPLIED", "APPROVED", "REWORK"]

AUTHORIZATION_STATUSES = ["VALID", "DEFECTIVE", "REVOKED", "EXPIRED", "SUPERSEDED"]
INVOICE_STATUSES = ["DRAFT", "ISSUED", "PAID", "WAIVED", "VOIDED"]
DELIVERY_STATUSES = ["PENDING", "SENT", "FAILED", "CONFIRMED", "RETURNED"]
DENIAL_STATUSES = ["ISSUED", "UNDER_REVIEW", "UPHELD", "OVERTURNED"]
AMENDMENT_STATUSES = ["SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "ACCEPTED", "DENIED"]

REQUESTER_TYPES = [
    "PATIENT",
    "PERSONAL_REPRESENTATIVE",
    "ATTORNEY",
    "INSURER",
    "EMPLOYER",
    "RESEARCHER",
    "GOVERNMENT_AGENCY",
    "OTHER_PROVIDER",
]
ACCESS_BASES = ["PATIENT_RIGHT_OF_ACCESS", "THIRD_PARTY_AUTHORIZATION"]
DELIVERY_FORMATS = ["PAPER_MAIL", "CD_ROM", "SECURE_PORTAL", "DIRECT_MESSAGE", "UNENCRYPTED_EMAIL", "FAX"]
ELECTRONIC_DELIVERY_FORMATS = ["SECURE_PORTAL", "DIRECT_MESSAGE", "UNENCRYPTED_EMAIL"]
SOURCE_SYSTEMS = ["EHR_CURRENT", "LEGACY_ARCHIVE", "IMAGING_PACS", "SCANNED_PAPER"]
ENCRYPTION_MODES = ["TLS", "AES256_ZIP", "NONE"]

RECORD_CATEGORIES = [
    "GENERAL_MEDICAL",
    "BEHAVIORAL_HEALTH",
    "SUD_PART2",
    "HIV",
    "GENETIC",
    "REPRODUCTIVE_HEALTH",
    "MINOR_CONFIDENTIAL",
    "PSYCHOTHERAPY_NOTES",
]

# The protected set a facility segregates by default.
DEFAULT_SENSITIVE_CATEGORIES = [
    "BEHAVIORAL_HEALTH",
    "SUD_PART2",
    "HIV",
    "GENETIC",
    "REPRODUCTIVE_HEALTH",
    "MINOR_CONFIDENTIAL",
    "PSYCHOTHERAPY_NOTES",
]

INVOICE_LINE_KINDS = [
    "BASE_RETRIEVAL",
    "PER_PAGE_TIER1",
    "PER_PAGE_TIER2",
    "PER_PAGE_FLAT",
    "LEGACY_RETRIEVAL",
    "CERTIFICATION",
    "MEDIA",
    "POSTAGE",
    "CAP_ADJUSTMENT",
    "LATE_FEE_FORFEITURE",
]

COMPLIANCE_EVENT_TYPES = [
    "STATUTORY_DEADLINE_BREACHED",
    "PENALTY_ACCRUED",
    "DENIAL_ISSUED",
    "DENIAL_OVERTURNED",
    "AUTHORIZATION_REVOKED",
    "AUTHORIZATION_EXPIRED",
    "SENSITIVE_WITHHOLD",
    "AMENDMENT_NOTICE_REQUIRED",
    "FEE_CAP_APPLIED",
    "DELIVERY_FAILED",
]

DENIAL_GROUNDS = [
    "NO_VALID_AUTHORIZATION",
    "PSYCHOTHERAPY_NOTES_EXCLUDED",
    "RECORD_NOT_MAINTAINED",
    "HARM_REVIEW_LICENSED_PROFESSIONAL",
    "INMATE_SAFETY",
    "RESEARCH_IN_PROGRESS",
]
DENIAL_GROUNDS_REVIEWABLE = ["HARM_REVIEW_LICENSED_PROFESSIONAL", "INMATE_SAFETY"]
VOID_REASONS = ["SUPERSEDED_BY_REPRICE", "AUTHORIZATION_REVOKED", "BILLING_CLERK_VOID"]

# ---------------------------------------------------------------- canonical fee schedule
# The California schedule every scenario in this suite prices against.
CA_FEE_RULE = {
    "state_code": "CA",
    "base_retrieval_fee_cents": 1500,
    "tier1_page_limit": 25,
    "tier1_per_page_millicents": 27500,
    "tier2_per_page_millicents": 12500,
    "patient_access_per_page_millicents": 10000,
    "certification_fee_cents": 1000,
    "media_fee_cents": 500,
    "postage_per_delivery_cents": 850,
    "electronic_delivery_total_cap_cents": 6500,
    "total_fee_cap_cents": 12000,
    "patient_access_deadline_days": 15,
    "third_party_deadline_days": 30,
    "extension_days": 15,
    "penalty_per_day_cents": 2500,
    "penalty_cap_cents": 25000,
    "fee_forfeiture_on_late": True,
}

# ---------------------------------------------------------------- canonical facility
CANONICAL_FACILITY = {
    "name": "Bay Regional Health",
    "legacy_archive_enabled": True,
    "legacy_retrieval_surcharge_cents": 2000,
    "legacy_gateway_job_minutes": 30,
    "legacy_gateway_buffer_minutes": 10,
}
