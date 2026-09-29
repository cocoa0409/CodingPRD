"""Business constants declared by the gift-card fraud and balance-protection PRD.

Every value here is a literal quoted from the PRD: the seeded risk-policy
defaults, the enumerations, the deterministic clock origin and the money /
scoring conventions.  Nothing is inferred.
"""

# ---------------------------------------------------------------------------
# Deterministic logical clock
# ---------------------------------------------------------------------------
# "The service runs on a deterministic logical clock which starts at exactly
# 2026-08-01T00:00:00Z."
CLOCK_ORIGIN = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Seeded RiskPolicy defaults (18 settings, singleton row)
# ---------------------------------------------------------------------------
POLICY_DEFAULTS = {
    "inquiry_velocity_window_minutes": 60,
    "inquiry_velocity_threshold": 5,
    "redemption_window_minutes": 1440,
    "drain_watch_score_threshold": 40,
    "drain_restrict_score_threshold": 70,
    "digital_hold_score_threshold": 45,
    "digital_decline_score_threshold": 75,
    "bulk_identity_threshold_cents": 50000,
    "bulk_quantity_limit": 25,
    "rack_shrink_threshold": 3,
    "rack_seal_break_threshold": 3,
    "floor_heightened_alert_threshold": 2,
    "claim_window_days": 90,
    "claim_evidence_round_limit": 3,
    "reissue_cap_cents": 100000,
    "recovery_factor_bps": 8500,
    "provisional_reserve_rate_bps": 3500,
    "final_reserve_rate_bps": 1000,
}

INQUIRY_VELOCITY_WINDOW_MINUTES = 60
INQUIRY_VELOCITY_THRESHOLD = 5
REDEMPTION_WINDOW_MINUTES = 1440
DRAIN_WATCH_SCORE_THRESHOLD = 40
DRAIN_RESTRICT_SCORE_THRESHOLD = 70
DIGITAL_HOLD_SCORE_THRESHOLD = 45
DIGITAL_DECLINE_SCORE_THRESHOLD = 75
BULK_IDENTITY_THRESHOLD_CENTS = 50000
BULK_QUANTITY_LIMIT = 25
RACK_SHRINK_THRESHOLD = 3
RACK_SEAL_BREAK_THRESHOLD = 3
FLOOR_HEIGHTENED_ALERT_THRESHOLD = 2
CLAIM_WINDOW_DAYS = 90
CLAIM_EVIDENCE_ROUND_LIMIT = 3
REISSUE_CAP_CENTS = 100000
RECOVERY_FACTOR_BPS = 8500
PROVISIONAL_RESERVE_RATE_BPS = 3500
FINAL_RESERVE_RATE_BPS = 1000

# ---------------------------------------------------------------------------
# Roles (§ identity and authorization)
# ---------------------------------------------------------------------------
ROLE_STORE_MANAGER = "StoreManager"
ROLE_POS_ASSOCIATE = "PosAssociate"
ROLE_FRAUD_ANALYST = "FraudAnalyst"
ROLE_RISK_MANAGER = "RiskManager"
ROLE_LIABILITY_ACCOUNTANT = "LiabilityAccountant"
ROLE_RESELLER_PARTNER = "ResellerPartner"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = [
    ROLE_STORE_MANAGER,
    ROLE_POS_ASSOCIATE,
    ROLE_FRAUD_ANALYST,
    ROLE_RISK_MANAGER,
    ROLE_LIABILITY_ACCOUNTANT,
    ROLE_RESELLER_PARTNER,
    ROLE_PLATFORM_ADMIN,
]

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
FLOOR_POSTURES = ["OPEN", "HEIGHTENED", "SUSPENDED"]
TAMPER_STATES = ["INTACT", "SUSPECT", "TAMPERED"]

CARD_CHANNELS = ["PHYSICAL", "DIGITAL"]
ACTIVATION_STATES = ["INACTIVE", "ACTIVE", "DEPLETED", "VOIDED", "CLOSED"]
RISK_POSTURES = ["CLEAR", "WATCH", "RESTRICTED", "FROZEN"]
# "CLEAR is the lowest rung, then WATCH, then RESTRICTED, then FROZEN."
RISK_POSTURE_RANK = {"CLEAR": 0, "WATCH": 1, "RESTRICTED": 2, "FROZEN": 3}

ISSUANCE_STATES = ["SUBMITTED", "APPROVED", "HELD_FOR_REVIEW", "DECLINED"]
DECLINE_REASONS = ["DIGITAL_RISK_SCORE", "MANUAL_DECLINE"]
PAYMENT_RISK_BANDS = ["LOW", "MEDIUM", "HIGH"]
SCREENING_COMPONENT_KEYS = ["device", "email", "payment", "amount", "base", "bulk_surcharge"]

BULK_ORDER_STATES = ["PENDING_IDENTITY", "IDENTITY_VERIFIED", "APPROVED", "DECLINED"]
PAYMENT_METHODS = ["CASH", "DEBIT", "CREDIT", "CORPORATE_ACH"]
ID_TYPES = ["DRIVERS_LICENSE", "PASSPORT", "STATE_ID", "MILITARY_ID"]
BULK_DECISIONS = ["APPROVE", "DECLINE", "REQUEST_INFO"]

CREDIT_EVENT_TYPES = [
    "ACTIVATION_LOAD",
    "REDEMPTION_REVERSAL",
    "REISSUE_CREDIT",
    "REISSUE_DEBIT_REVERSAL",
]
DEBIT_EVENT_TYPES = ["REDEMPTION", "REISSUE_DEBIT", "REISSUE_CREDIT_REVERSAL"]
LEDGER_EVENT_TYPES = CREDIT_EVENT_TYPES + DEBIT_EVENT_TYPES

HOLD_STATES = ["ACTIVE", "RELEASED", "CAPTURED", "EXPIRED"]
HOLD_DISPOSITIONS = ["RELEASE", "CAPTURE"]

INQUIRY_CHANNELS = ["POS", "IVR", "WEB", "MOBILE", "RESELLER_API"]

ALERT_STATES = ["OPEN", "TRIAGED", "CONFIRMED", "DISMISSED"]
DETECTION_BASES = [
    "INQUIRY_VELOCITY",
    "REDEMPTION_PATTERN",
    "RESELLER_SIGNAL",
    "MANUAL_REVIEW",
]
ALERT_RESOLUTIONS = ["CONFIRM", "DISMISS"]

LISTING_STATES = ["SUBMITTED", "VALIDATED", "REJECTED", "BLOCKED"]
LISTING_BLOCK_REASONS = [
    "CARD_NOT_ACTIVE",
    "CARD_RISK_POSTURE",
    "BALANCE_MISMATCH",
    "DRAIN_SCORE",
]

CLAIM_STATES = ["SUBMITTED", "EVIDENCE_REQUESTED", "APPROVED", "DENIED", "RESCINDED"]
CLAIM_DECISIONS = ["APPROVE", "DENY"]
EVIDENCE_KINDS = ["PURCHASE_RECEIPT", "PACKAGING_PHOTO"]

PERIOD_STATES = ["OPEN", "CLOSED", "RESTATED"]

# ---------------------------------------------------------------------------
# Envelope / pagination conventions
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# "a well formed but absent identifier"
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"

# Entities declared with only id and created_at (no updated_at, no version).
CREATE_ONLY_ENTITIES = ["LedgerEvent", "BalanceInquiry", "LawEnforcementReferral"]
