"""Domain constants for the condominium conversion registry API.

Every value here is quoted from the PRD (roles, section codes, statutory
windows, pagination bounds). Tests import these instead of repeating literals.
"""

# --- Logical clock -----------------------------------------------------------
# "Every server process starts with its logical clock at exactly
#  2026-08-01T00:00:00Z."
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# --- Roles -------------------------------------------------------------------
ROLE_CONVERTER_SPONSOR = "ConverterSponsor"
ROLE_LICENSED_ENGINEER = "LicensedEngineer"
ROLE_PEER_REVIEW_ENGINEER = "PeerReviewEngineer"
ROLE_STATE_REGULATOR = "StateRegulator"
ROLE_ESCROW_AGENT = "EscrowAgent"
ROLE_LENDER_UNDERWRITER = "LenderUnderwriter"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_TENANT_OCCUPANT = "TenantOccupant"
ROLE_PURCHASER = "Purchaser"

ALL_ROLES = (
    ROLE_CONVERTER_SPONSOR,
    ROLE_LICENSED_ENGINEER,
    ROLE_PEER_REVIEW_ENGINEER,
    ROLE_STATE_REGULATOR,
    ROLE_ESCROW_AGENT,
    ROLE_LENDER_UNDERWRITER,
    ROLE_PLATFORM_ADMIN,
    ROLE_TENANT_OCCUPANT,
    ROLE_PURCHASER,
)

# The seven roles whose X-User-ID is an opaque string of the caller's choosing.
# TenantOccupant and Purchaser are entity-backed: their X-User-ID must be the
# id of the TenantHousehold / PurchaseAgreement they are acting for.
OPAQUE_ROLES = (
    ROLE_CONVERTER_SPONSOR,
    ROLE_LICENSED_ENGINEER,
    ROLE_PEER_REVIEW_ENGINEER,
    ROLE_STATE_REGULATOR,
    ROLE_ESCROW_AGENT,
    ROLE_LENDER_UNDERWRITER,
    ROLE_PLATFORM_ADMIN,
)
ENTITY_BACKED_ROLES = (ROLE_TENANT_OCCUPANT, ROLE_PURCHASER)

# --- Conventional opaque user ids used by the tests --------------------------
SPONSOR_USER_ID = "sponsor-1"
SPONSOR_ALT_USER_ID = "sponsor-0"
ENGINEER_USER_ID = "eng-1"
ENGINEER_ALT_USER_ID = "eng-2"
PEER_USER_ID = "peer-1"
REGULATOR_USER_ID = "reg-1"
ESCROW_USER_ID = "escrow-1"
LENDER_USER_ID = "lender-1"
ADMIN_USER_ID = "admin-1"
# Used only where a Purchaser/TenantOccupant is denied before any entity is
# consulted; never used to act on an entity-backed resource.
UNBOUND_PURCHASER_USER_ID = "buyer-1"
UNBOUND_TENANT_USER_ID = "tenant-1"

# --- Public offering statement sections -------------------------------------
POS_SECTION_CODES = (
    "UNIT_BOUNDARIES",
    "COMMON_ELEMENTS",
    "PERCENTAGE_INTERESTS",
    "BUDGET",
    "RESERVES",
    "ENGINEERING_CONDITION",
    "TENANT_RIGHTS",
    "WARRANTY",
    "RESCISSION_RIGHTS",
)
POS_SECTION_MIN_WORD_COUNT = 150
POS_REQUIRED_SECTION_COUNT = 9

# --- Enumerations -----------------------------------------------------------
COMPONENT_TYPES = (
    "ROOF",
    "ELEVATOR",
    "HVAC",
    "PLUMBING_RISERS",
    "ELECTRICAL_SERVICE",
    "FACADE",
    "FOUNDATION",
    "PARKING_DECK",
    "FIRE_SUPPRESSION",
)
CONDITION_RATINGS = ("EXCELLENT", "GOOD", "FAIR", "POOR")
BOUNDARY_CONVENTIONS = ("PAINT_TO_PAINT", "STUD_TO_STUD", "CENTERLINE")
PURCHASER_TYPES = ("OWNER_OCCUPANT", "INVESTOR")
PROTECTED_CLASSES = ("NONE", "HOUSEHOLD_WITH_MINOR", "ELDERLY", "DISABLED")
RESERVE_METHODS = ("COMPONENT_METHOD", "CASH_FLOW_METHOD")
SUITABILITY_VARIANTS = ("AS_INSPECTED", "POST_REMEDIATION")

# --- Pagination -------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# --- Numeric rules ----------------------------------------------------------
TOTAL_UNDIVIDED_INTEREST_BP = 10000
SUITABILITY_PASSING_SCORE = "62.50"
SUITABILITY_HORIZON_YEARS = 30
LIFE_SAFETY_MIN_REMAINING_YEARS = 5
CRITICAL_CAP_RAW_SCORE = "0.40"
RESERVE_FLOOR_CENTS_PER_UNIT = 25000
RESERVE_HORIZON_YEARS = 30
RESERVE_ADEQUATE_MIN_BP = 7000
MANAGEMENT_FEE_TIER_BP = (800, 650, 500)
WARRANTY_STRUCTURAL_SECONDS = 155520000
WARRANTY_NON_STRUCTURAL_SECONDS = 62208000
REMEDIATION_COOLDOWN_SECONDS = 259200
TRIAGE_ACCRUAL_CAP_BP = 6000
REOPEN_UPLIFT_BP = 2500
CLAIM_REOPEN_LIMIT = 2
ROFR_WINDOW_DAYS = 90
RESCISSION_DAYS_OWNER_OCCUPANT = 15
RESCISSION_DAYS_INVESTOR = 7
NOTICE_DAYS_BY_TENURE = (120, 180, 270)
PROTECTED_CLASS_EXTRA_DAYS = (0, 45, 90)
RELOCATION_ASSISTANCE_CAP_CENTS = 1500000
RELOCATION_ASSISTANCE_FLOOR_CENTS = 250000

# --- Common fields carried by every entity ----------------------------------
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
