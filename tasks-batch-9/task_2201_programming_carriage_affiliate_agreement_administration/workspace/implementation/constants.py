"""Domain constants for the Carriage Affiliate Admin API.

Every value here is taken verbatim from the PRD / scaffold domain_constants
block.  Nothing in this module is entity data -- these are pure configuration
values of the pricing, compliance and rights engines.
"""
from decimal import Decimal

# --- precision -------------------------------------------------------------
RATE_PRECISION = 4
MONEY_PRECISION = 0

# --- escalator -------------------------------------------------------------
CONTRACT_YEAR_DAYS = 365

# --- packaging tiers -------------------------------------------------------
TIER_MULTIPLIER = {
    "BASIC": Decimal("1.00"),
    "EXPANDED_BASIC": Decimal("1.00"),
    "DIGITAL_TIER": Decimal("0.85"),
    "PREMIUM": Decimal("0.60"),
}
TIER_RANK = {"BASIC": 4, "EXPANDED_BASIC": 3, "DIGITAL_TIER": 2, "PREMIUM": 1}
TIERS = ["BASIC", "EXPANDED_BASIC", "DIGITAL_TIER", "PREMIUM"]

# --- penetration compliance ------------------------------------------------
PENETRATION_BREACH_SUSPEND_THRESHOLD = 2
PENETRATION_COMPLIANT_RESET_RUN = 3

# --- rights windows --------------------------------------------------------
MAX_CONCURRENT_NONEXCLUSIVE = 3
PLATFORM_HOLDBACK_DAYS = {"LINEAR": 0, "VOD": 1, "STREAMING": 7, "INTERNATIONAL": 30}
PLATFORMS = ["LINEAR", "VOD", "STREAMING", "INTERNATIONAL"]
EXCLUSIVITIES = ["EXCLUSIVE", "NON_EXCLUSIVE"]

# --- blackouts -------------------------------------------------------------
BLACKOUT_MIN_SEPARATION_HOURS = 24
MAX_BLACKOUT_HOURS_PER_MONTH = Decimal("72")

# --- audit -----------------------------------------------------------------
MONTHLY_INTEREST_PCT = Decimal("0.0075")
AUDIT_COST_CENTS = 2500000
AUDIT_COST_SHIFT_THRESHOLD = Decimal("0.05")
PENALTY_TIER_1_THRESHOLD = Decimal("0.05")
PENALTY_TIER_2_THRESHOLD = Decimal("0.10")
AUDIT_RIGHTS_SURVIVAL_MONTHS = 24

# --- invoice co-op bands ---------------------------------------------------
COOP_BAND_1_MAX = 5000000
COOP_BAND_2_MAX = 25000000
COOP_CAP_BAND_1 = Decimal("0.05")
COOP_CAP_BAND_2 = Decimal("0.08")
COOP_CAP_BAND_3 = Decimal("0.12")

# --- renewal ---------------------------------------------------------------
RENEWAL_WINDOW_DAYS = 270
RENEWAL_TERM_MONTHS = 36

# --- receivables -----------------------------------------------------------
WRITE_OFF_AGE_DAYS = 120

# --- marketing -------------------------------------------------------------
LAUNCH_FEE_PERFORMANCE_DAYS = 180

# --- renewal leverage model ------------------------------------------------
TOTAL_ADDRESSABLE_SUBS = 90000000
SHARE_SATURATION = Decimal("0.15")
PENETRATION_SATURATION = Decimal("1.5")
BREACH_SCORE_DENOMINATOR = Decimal("3")
W_SHARE = Decimal("0.40")
W_PENETRATION = Decimal("0.25")
W_PAYMENT = Decimal("0.20")
W_COMPLIANCE = Decimal("0.15")
RECAPTURE_RATE_BASE = Decimal("0.35")
RECAPTURE_RATE_DOWNSIDE = Decimal("0.10")

# --- MFN benchmark ---------------------------------------------------------
SCOPE_TYPES = {
    "DOMESTIC": ["CABLE_MSO", "DBS", "TELCO"],
    "GLOBAL": ["CABLE_MSO", "DBS", "TELCO", "VMVPD"],
}
VOLUME_BAND_FACTOR = {
    "SMALL": Decimal("1.05"),
    "MID": Decimal("1.00"),
    "LARGE": Decimal("0.94"),
}
VMVPD_PLATFORM_DISCOUNT = Decimal("0.08")

# --- logical clock ---------------------------------------------------------
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# --- enumerations ----------------------------------------------------------
ROLES = [
    "AffiliateSalesExec",
    "DistributorLiaison",
    "RevenueAccountant",
    "AuditManager",
    "RightsAdministrator",
    "NetworkAdmin",
]
DISTRIBUTOR_TYPES = ["CABLE_MSO", "DBS", "TELCO", "VMVPD"]
RATE_CARD_CLASSES = ["CLASS_A", "CLASS_B", "CLASS_C"]
DISTRIBUTOR_STATUSES = ["ACTIVE", "CREDIT_HOLD", "SUSPENDED", "TERMINATED"]
CREDIT_HOLD_REASONS = [
    "NONE",
    "RECEIVABLE_LIMIT_BREACH",
    "AUDIT_RECOVERY_UNPAID",
    "MANUAL_REVIEW",
]
LIFECYCLE_STATUSES = [
    "DRAFT",
    "NEGOTIATING",
    "EXECUTED",
    "SUSPENDED",
    "EXPIRED",
    "TERMINATED",
]
RENEWAL_STATUSES = [
    "NOT_DUE",
    "RENEWAL_ANALYSIS",
    "RENEWAL_OFFERED",
    "RENEWED",
    "LAPSED",
]
SUSPENSION_REASONS = [
    "NONE",
    "PENETRATION_BREACH",
    "DISTRIBUTOR_CREDIT_HOLD",
    "MANUAL_SUSPENSION",
]
MFN_SCOPES = ["DOMESTIC", "GLOBAL"]
MFN_STATUSES = ["ACTIVE", "WAIVED"]
BENCHMARK_STATUSES = ["NOT_EVALUATED", "BENCHMARKED", "NO_COMPARABLE"]
REPORT_STATUSES = [
    "SUBMITTED",
    "DISPUTED",
    "RESTATED",
    "ACCEPTED",
    "AUDIT_ADJUSTED",
    "SUPERSEDED",
]
RATE_BASES = ["PERIOD_RATE", "CLOSING_RATE"]
ENGAGEMENT_STATUSES = [
    "OPENED",
    "FIELDWORK",
    "FINDINGS_ISSUED",
    "RECOVERY_INVOICED",
    "COLLECTED",
    "CLOSED_NO_FINDING",
]
RIGHTS_STATUSES = [
    "PENDING_CLEARANCE",
    "OWNED_CLEARED",
    "THIRD_PARTY_LICENSED",
    "EXPIRED_RIGHTS",
]
COVERAGE_STATUSES = [
    "UNDISTRIBUTED",
    "LINEAR_ONLY",
    "MULTIPLATFORM",
    "EXCLUSIVE_UNCLEARED",
]
WINDOW_STATUSES = ["PLANNED", "CLEARED", "ACTIVE", "BLOCKED", "EXPIRED"]
BLOCK_REASONS = [
    "NONE",
    "AGREEMENT_SUSPENDED",
    "BLACKOUT_CONFLICT",
    "RIGHTS_LAPSED",
    "MANUAL_BLOCK",
]
BLACKOUT_STATUSES = ["SCHEDULED", "ENFORCED", "WAIVED", "EXPIRED"]
COMMITMENT_TYPES = ["LAUNCH_FEE", "COOP_ADVERTISING", "MARKETING_SUPPORT"]
COMMITMENT_STATUSES = [
    "OPEN",
    "PARTIALLY_EARNED",
    "EARNED",
    "FORFEITED",
    "SETTLED",
]
INVOICE_KINDS = ["LICENSE_FEE", "AUDIT_RECOVERY"]
INVOICE_STATUSES = [
    "DRAFT",
    "ISSUED",
    "PARTIALLY_PAID",
    "PAID",
    "WRITTEN_OFF",
    "VOID",
]
RENEWAL_VARIANTS = ["BASE_CASE", "DOWNSIDE"]

ALL_ROLES = list(ROLES)
