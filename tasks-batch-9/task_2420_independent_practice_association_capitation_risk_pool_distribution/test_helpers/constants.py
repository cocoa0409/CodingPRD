"""Domain constants for the IPA Capitation & Risk Pool Distribution API.

Every value here is transcribed from the PRD. Nothing is invented.
"""

# ---------------------------------------------------------------------------
# Roles (PRD §2.1 — the six recognised roles, spelled exactly)
# ---------------------------------------------------------------------------
ROLE_IPA_ADMIN = "IpaAdmin"
ROLE_NETWORK_MANAGER = "NetworkManager"
ROLE_CLAIMS_EXAMINER = "ClaimsExaminer"
ROLE_REINSURANCE_UNDERWRITER = "ReinsuranceUnderwriter"
ROLE_PHYSICIAN_USER = "PhysicianUser"
ROLE_PAYER_REPRESENTATIVE = "PayerRepresentative"

ALL_ROLES = [
    ROLE_IPA_ADMIN,
    ROLE_NETWORK_MANAGER,
    ROLE_CLAIMS_EXAMINER,
    ROLE_REINSURANCE_UNDERWRITER,
    ROLE_PHYSICIAN_USER,
    ROLE_PAYER_REPRESENTATIVE,
]

# Roles whose X-User-ID is an opaque operator identifier (PRD §2.1).
OPAQUE_IDENTITY_ROLES = [
    ROLE_IPA_ADMIN,
    ROLE_NETWORK_MANAGER,
    ROLE_CLAIMS_EXAMINER,
    ROLE_REINSURANCE_UNDERWRITER,
]

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------
CLOCK_STARTUP_INSTANT = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Basis points (PRD §2.6)
# ---------------------------------------------------------------------------
BPS_PAR = 10000

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
DELEGATION_SCOPES = ["CLAIMS_ONLY", "CLAIMS_AND_UM", "FULL_RISK"]
RECONCILIATION_METHODS = ["ROSTER_SNAPSHOT", "MEMBER_MONTHS_PRORATED"]
IBNR_METHODS = ["COMPLETION_FACTOR", "PMPM_LOSS_RATIO"]
AGREEMENT_STATUSES = ["DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED"]
CAPITATION_POSTURES = ["CURRENT", "UNDER_REVIEW", "WITHHELD"]

SPECIALTIES = ["PRIMARY_CARE", "PEDIATRICS", "INTERNAL_MEDICINE", "OB_GYN"]
CREDENTIAL_STATUSES = ["APPLICANT", "CREDENTIALED", "ACTIVE", "NOTICE_GIVEN", "EXITED"]
PANEL_STATUSES = ["OPEN", "CLOSED_TO_NEW", "TRANSFER_PENDING", "TRANSFERRED"]

AGE_BANDS = ["PEDIATRIC", "ADULT", "SENIOR"]
BENEFIT_TIERS = ["HMO", "POS", "HMO_PLUS"]

ASSIGNMENT_SOURCES = ["MANUAL", "ENROLLMENT_FILE", "PANEL_TRANSFER"]
ASSIGNMENT_STATUSES = [
    "ACTIVE",
    "TRANSFER_PROPOSED",
    "TRANSFER_ACCEPTED",
    "TRANSFERRED",
    "TERMINATED",
]

FILE_STATUSES = ["RECEIVED", "PARSED", "RECONCILED", "DISPUTED", "POSTED"]
ROW_ACTIONS = ["ADD", "TERM", "CHANGE", "RETRO_ADD", "RETRO_TERM"]
MATCH_STATUSES = [
    "UNMATCHED",
    "MATCHED_ENROLLEE_ONLY",
    "EXCEPTION_PHYSICIAN_INACTIVE",
    "MATCHED",
]

REMITTANCE_STATUSES = ["RECONCILED", "DISPUTED", "POSTED"]

POOL_TYPES = ["PROFESSIONAL", "INSTITUTIONAL"]
POOL_STATUSES = [
    "ACCUMULATING",
    "CLOSED_FOR_INCURRAL",
    "RESERVED",
    "SETTLEMENT_PROPOSED",
    "SETTLED",
]
SURPLUS_TIERS = ["NONE", "TIER_1", "TIER_2", "TIER_3"]

CLAIM_STATUSES = [
    "RECEIVED",
    "ADJUDICATED_APPROVED",
    "ADJUDICATED_DENIED",
    "PAID",
    "VOIDED",
]
DENIAL_REASONS = ["NOT_COVERED", "DUPLICATE", "NO_AUTHORIZATION"]

RECOVERY_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "DENIED", "RECOVERED"]
RECOVERY_DENIAL_REASONS = ["BELOW_ATTACHMENT", "LATE_FILING", "POOL_SETTLED"]

SCORECARD_STATUSES = ["DRAFT", "FINAL", "SUPERSEDED"]
DISTRIBUTION_STATUSES = ["PROPOSED", "PAID", "VOIDED"]

# ---------------------------------------------------------------------------
# Per-member capitation derivation (PRD §3.3)
# ---------------------------------------------------------------------------
AGE_BAND_FACTOR_BPS = {"PEDIATRIC": 6500, "ADULT": 10000, "SENIOR": 14500}
BENEFIT_TIER_ADDON_CENTS = {"HMO": 0, "POS": 1200, "HMO_PLUS": 2500}
PMPM_FLOOR_CENTS = 8000
PMPM_CEILING_CENTS = 95000

# ---------------------------------------------------------------------------
# Pool loss ratio and deficit (PRD §3.5)
# ---------------------------------------------------------------------------
POOL_DEFICIT_LOSS_RATIO_BPS = 9500

# ---------------------------------------------------------------------------
# Downstream claim appeals (PRD §3.6)
# ---------------------------------------------------------------------------
APPEAL_LIMIT = 2

# ---------------------------------------------------------------------------
# Settlement lag by pool type, in days (PRD §3.7)
# ---------------------------------------------------------------------------
SETTLEMENT_LAG_DAYS = {"PROFESSIONAL": 180, "INSTITUTIONAL": 270}

# ---------------------------------------------------------------------------
# Continuity of care default (PRD §3.1)
# ---------------------------------------------------------------------------
DEFAULT_CONTINUITY_OF_CARE_DAYS = 90

# ---------------------------------------------------------------------------
# Quality composite weights and withhold-release bands (PRD §3.8)
# ---------------------------------------------------------------------------
COMPOSITE_WEIGHT_HEDIS_BPS = 5000
COMPOSITE_WEIGHT_PATIENT_EXPERIENCE_BPS = 3000
COMPOSITE_WEIGHT_ACCESS_BPS = 2000

# Ordered high to low; each band uses an at-or-above comparison.
WITHHOLD_RELEASE_BANDS = [(8500, 10000), (7000, 7500), (5500, 5000)]
WITHHOLD_RELEASE_BELOW_ALL_BANDS_BPS = 0

# ---------------------------------------------------------------------------
# Settlement waterfall tiers (PRD §3.8)
# ---------------------------------------------------------------------------
SURPLUS_TIER_1_MAX_RATIO_BPS = 500
SURPLUS_TIER_2_MAX_RATIO_BPS = 1500

ADMIN_FEE_BPS_BY_TIER = {"NONE": 0, "TIER_1": 300, "TIER_2": 600, "TIER_3": 1000}
SHARED_SAVINGS_SHARE_BPS_BY_TIER = {
    "NONE": 0,
    "TIER_1": 4000,
    "TIER_2": 5000,
    "TIER_3": 6000,
}

# ---------------------------------------------------------------------------
# Common field sets (PRD §2.4)
# ---------------------------------------------------------------------------
VERSIONED_AUDIT_FIELDS = ["id", "created_at", "updated_at", "version"]
# EnrollmentFileRow is the single exception: it carries only id and created_at.
ROW_AUDIT_FIELDS = ["id", "created_at"]
