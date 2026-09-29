"""Named constants of the biometric privacy consent program contract.

Every value here is a figure the API contract fixes; nothing is invented.
"""

# ----------------------------------------------------------------------
# Roles
# ----------------------------------------------------------------------
ROLE_SYSTEM_OPERATOR = "SystemOperator"
ROLE_PRIVACY_OFFICER = "PrivacyOfficer"
ROLE_COMPLIANCE_APPROVER = "ComplianceApprover"
ROLE_VENDOR_MANAGER = "VendorManager"
ROLE_HR_ADMINISTRATOR = "HRAdministrator"
ROLE_SUBJECT = "Subject"

ALL_ROLES = [
    ROLE_SYSTEM_OPERATOR,
    ROLE_PRIVACY_OFFICER,
    ROLE_COMPLIANCE_APPROVER,
    ROLE_VENDOR_MANAGER,
    ROLE_HR_ADMINISTRATOR,
    ROLE_SUBJECT,
]

# ----------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"
DEFAULT_CLOCK_INPUT = "2026-08-01T00:00:00Z"

# ----------------------------------------------------------------------
# Enumerations
# ----------------------------------------------------------------------
ORG_TYPES = ["EMPLOYER", "RETAILER", "HYBRID"]
POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
PRIVATE_RIGHT_OF_ACTION = ["NONE", "LIMITED", "FULL"]
DAMAGES_MODELS = ["STATUTORY_PER_VIOLATION", "ACTUAL_ONLY"]
ATTESTATION_STATUSES = ["NOT_REQUESTED", "REQUESTED", "RECEIVED", "REJECTED"]
CONTRACT_STATUSES = ["DRAFT", "APPROVED", "EXECUTED", "TERMINATED", "CLOSED_OUT", "VOID"]
POLICY_STATUSES = ["DRAFT", "IN_REVIEW", "PUBLISHED", "SUPERSEDED", "RETIRED"]
NOTICE_STATUSES = ["DRAFT", "PUBLISHED", "WITHDRAWN"]
ASSET_STATUSES = ["DISCOVERED", "CLASSIFIED", "ACTIVE", "GATED", "DECOMMISSIONED"]
CONSENT_STATUSES = ["SOLICITED", "GRANTED", "DECLINED", "REVOKED", "EXPIRED", "RESOLICIT_REQUIRED"]
ACCOMMODATION_STATUSES = ["REQUESTED", "PROVISIONED", "ACTIVE", "ENDED", "REJECTED"]
ACCOMMODATION_ORIGINS = ["MANUAL", "AUTO_DECLINE", "AUTO_REVOKE", "AUTO_CONSENT_EXPIRY"]
CONTAINMENT_STATUSES = ["DETECTED", "CONTAINED", "REMEDIATED"]
NOTIFICATION_STATUSES = ["PENDING", "ASSESSED", "NOTIFIED", "EXEMPT"]
ASSESSMENT_STATUSES = ["DRAFT", "FINAL", "VOID"]
ENROLLMENT_STATUSES = ["NOT_ENROLLED", "ENROLLED", "ALTERNATIVE", "OPTED_OUT"]
SYSTEM_CATEGORIES = ["TIMEKEEPING", "ACCESS_CONTROL", "CUSTOMER_FACING", "SECURITY_CAMERA"]
MODALITIES = ["FINGERPRINT", "FACE_GEOMETRY", "IRIS", "VOICEPRINT", "HAND_GEOMETRY"]
SUBJECT_CLASSES = ["EMPLOYEE", "CUSTOMER"]
RETENTION_BASES = ["SCHEDULE_ONLY", "PURPOSE_LIMITED"]
DESTRUCTION_TRIGGERS = ["FIXED_SCHEDULE", "PURPOSE_SATISFIED_OR_MAX"]
EXPOSURE_VARIANTS = ["PER_VIOLATION_STACKED", "PER_SUBJECT_CAPPED"]
HEIGHTENED_TIERS = ["TIER_1", "TIER_2"]

# ----------------------------------------------------------------------
# Retention and destruction
# ----------------------------------------------------------------------
PURPOSE_GRACE_DAYS = 7

# ----------------------------------------------------------------------
# PRA exposure estimate
# ----------------------------------------------------------------------
PRA_FACTOR = {"NONE": 0.00, "LIMITED": 0.50, "FULL": 1.00}
NOTICE_GAP_MULTIPLIER = 1.25
CURE_CREDIT_PCT = 0.30
PER_SUBJECT_CAP_CENTS = 300000

# ----------------------------------------------------------------------
# Vendor contract compliance score
# ----------------------------------------------------------------------
W_PROHIBITS_SALE = 0.35
W_RESTRICTS_DISCLOSURE = 0.25
W_DELETION_ON_TERM = 0.30
W_DELETION_SLA = 0.10
DELETION_DEADLINE_TARGET_DAYS = 30
ATTESTATION_FACTOR = {
    "NOT_REQUESTED": 0.715,
    "REQUESTED": 0.855,
    "RECEIVED": 1.000,
    "REJECTED": 0.000,
}
SELL_PENALTY_POINTS = 7.5
SUBPROCESSOR_PENALTY_POINTS = 2.5
SUBPROCESSOR_PENALTY_CAP = 4
CONTRACT_SCORE_FLOOR = 82.50

# ----------------------------------------------------------------------
# Vendor risk score
# ----------------------------------------------------------------------
RISK_BASE = 20
RISK_SELLS_POINTS = 30
RISK_SUBPROCESSOR_POINTS = 5
RISK_SUBPROCESSOR_CAP = 6
RISK_SLA_POINTS = 15
RISK_SLA_TARGET_DAYS = 30
RISK_ATTESTATION_POINTS = {"NOT_REQUESTED": 20, "REQUESTED": 10, "RECEIVED": 0, "REJECTED": 35}
RISK_DISCLOSURE_GAP_POINTS = 10
VENDOR_RISK_GATE = 70

# ----------------------------------------------------------------------
# Incident notification deadline and cost
# ----------------------------------------------------------------------
TIER1_SUBJECT_THRESHOLD = 500
TIER1_DEADLINE_DAYS = 15
TIER2_DEADLINE_DAYS = 45
NOTICE_UNIT_CENTS = 425
TRANSLATION_UNIT_CENTS = 15000
SURCHARGE_MID_FLOOR_CENTS = 50000
SURCHARGE_HIGH_FLOOR_CENTS = 150000
SURCHARGE_MID_CENTS = 25000
SURCHARGE_HIGH_CENTS = 75000
INDEMNITY_CREDIT_PCT = 0.50
TIER1_MODALITIES = ["FACE_GEOMETRY", "IRIS"]

# ----------------------------------------------------------------------
# Program posture
# ----------------------------------------------------------------------
POSTURE_FREEZE_EXPOSURE_PCT = 80

# ----------------------------------------------------------------------
# Accommodations and consent records
# ----------------------------------------------------------------------
ACCOMMODATION_METHOD_MAP = {
    "TIMEKEEPING": "MANUAL_TIMESHEET",
    "ACCESS_CONTROL": "BADGE_PIN",
    "CUSTOMER_FACING": "STAFFED_LANE",
    "SECURITY_CAMERA": "MANUAL_LOG",
}
ACCOMMODATION_METHODS = sorted(set(ACCOMMODATION_METHOD_MAP.values()))
ACCOMMODATION_SLA_DAYS = 5
AUTO_ACCOMMODATION_WINDOW_DAYS = 90
ACCOMMODATION_CHANGEOVER_BUFFER_HOURS = 24
CONSENT_RECORD_RETENTION_DAYS = 1095

# ----------------------------------------------------------------------
# Canonical statutory profiles used by the fixtures
# ----------------------------------------------------------------------
ILLINOIS_PROFILE = {
    "state_code": "IL",
    "statute_name": "BIPA",
    "private_right_of_action": "FULL",
    "damages_model": "STATUTORY_PER_VIOLATION",
    "requires_written_release": True,
    "translation_required": True,
    "required_locales": ["en", "es"],
    "retention_max_days": 1095,
    "notice_lead_days": 14,
    "per_violation_negligent_cents": 100000,
    "per_violation_reckless_cents": 500000,
    "cure_period_days": 0,
}

DEFAULT_EXPOSURE_CEILING_CENTS = 1093750
DEFAULT_ORG_NAME = "Northline Retail Group"
DEFAULT_ORG_TYPE = "HYBRID"
DEFAULT_ACCOMMODATION_CHANNEL = "privacy@northline.example"
