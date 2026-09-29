"""
Domain constants for the Ground Lease Administration API test suite.

Every value here is transcribed from PRD.md (workspace/PRD.md) — the roles of
§2.1, the pagination envelope of §2.3, the logical clock of §2.5, the integer
money/basis-point rules of §2.6 and the named constants of §3.
"""

API_PREFIX = "/portfolio"
CLOCK_PATH = "/_clock/set_current_utc"

# --- §2.1 Roles (spelled exactly as the PRD spells them) -------------------
ROLE_LESSOR_ADMIN = "LessorAdmin"
ROLE_ASSET_MANAGER = "AssetManager"
ROLE_LEASE_ACCOUNTANT = "LeaseAccountant"
ROLE_GROUND_TENANT = "GroundTenant"
ROLE_MORTGAGEE_AGENT = "MortgageeAgent"
ROLE_ARBITRATOR = "Arbitrator"

ALL_ROLES = [
    ROLE_LESSOR_ADMIN,
    ROLE_ASSET_MANAGER,
    ROLE_LEASE_ACCOUNTANT,
    ROLE_GROUND_TENANT,
    ROLE_MORTGAGEE_AGENT,
    ROLE_ARBITRATOR,
]

# --- §2.3 Pagination -------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- §2.5 Logical clock ----------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --- §2.6 Basis points -----------------------------------------------------
BPS_WHOLE = 10000
MIN_CONDITION_SCORE = 0
MAX_CONDITION_SCORE = 100

# --- §3.3 Revaluation ------------------------------------------------------
REVALUATION_ADVANCE_NOTICE_DAYS = 180
ARBITRATION_DIVERGENCE_THRESHOLD_BPS = 1000
MAX_NEGOTIATION_ROUNDS = 2

# --- §3.4 Percentage rent --------------------------------------------------
SUBLEASE_INCLUSION_RATE_BPS = 5000
BASE_RENT_OFFSET_SHARE_BPS = 2500
UNDERREPORT_TOLERANCE_BPS = 500

# --- §3.6 Transfers --------------------------------------------------------
ASSIGNMENT_TIER1_CEILING_CENTS = 50000000
ASSIGNMENT_TIER2_CEILING_CENTS = 200000000
MIN_ASSIGNMENT_FEE_CENTS = 500000
SUBLEASE_PROFIT_SHARE_BPS = 5000
ADMIN_CHARGE_BPS = 250
ADMIN_CHARGE_CAP_CENTS = 250000
LATE_SURCHARGE_TIER_CEILING_CENTS = 1000000
LATE_SURCHARGE_LOW_BPS = 250
LATE_SURCHARGE_HIGH_BPS = 500
MAX_SUBLEASE_TIER_DEPTH = 2
SUBLEASE_TURNOVER_BUFFER_DAYS = 0
DAYS_PER_YEAR_BASIS = 365

# --- §3.7 Default / casualty ----------------------------------------------
MONETARY_CURE_DAYS = 10
INSURANCE_CURE_DAYS = 15
NON_MONETARY_CURE_DAYS = 30
NEW_LEASE_ELECTION_DAYS = 30
CASUALTY_TERMINATION_THRESHOLD_BPS = 5000

# --- §3.9 Reversion -------------------------------------------------------
MAX_COMPONENT_SCORE = 100
REVERSION_STANDARDS = {
    "SHELL_CONDITION": {
        "structural_bps": 6000,
        "envelope_bps": 3000,
        "systems_bps": 1000,
        "passing_score_bps": 7000,
    },
    "FULLY_FITTED": {
        "structural_bps": 4000,
        "envelope_bps": 3000,
        "systems_bps": 3000,
        "passing_score_bps": 8500,
    },
    "BROOM_CLEAN": {
        "structural_bps": 7000,
        "envelope_bps": 2000,
        "systems_bps": 1000,
        "passing_score_bps": 6000,
    },
}

# --- Enumerations ---------------------------------------------------------
CREDIT_RATINGS = ["AAA", "A", "BBB", "SPECULATIVE"]
LEASE_STATUSES = ["ACTIVE", "IN_DEFAULT", "TERMINATED", "EXPIRED", "REVERTED"]
RENT_STATUSES = [
    "BASE_ONLY",
    "REVALUATION_DUE",
    "REVALUATION_OPEN",
    "IN_ARBITRATION",
    "RESET_APPLIED",
    "FROZEN",
]
INSURANCE_STATUSES = ["ACTIVE", "LAPSED"]
PERMITTED_USE_CODES = [
    "RETAIL_MIXED",
    "OFFICE",
    "INDUSTRIAL",
    "RESIDENTIAL",
    "HOSPITALITY",
]
ALTERATION_SCOPES = ["COSMETIC", "STRUCTURAL_ALTERATION", "REDEVELOPMENT"]
TRANSFER_TYPES = ["ASSIGNMENT", "SUBLEASE"]
LOSS_EVENT_TYPES = ["CASUALTY", "CONDEMNATION"]
LOSS_SCOPES = ["PARTIAL", "TOTAL"]
ALLOCATION_METHODS = ["BONUS_VALUE", "PRO_RATA_VALUE"]
APPOINTED_BY = ["LESSOR", "LESSEE"]
VALUATION_METHODS = ["COMPARABLE_LAND", "INCOME_CAP", "RESIDUAL_LAND"]
DEFAULT_TYPES = [
    "MONETARY_RENT_ARREARS",
    "INSURANCE_LAPSE",
    "UNPERMITTED_USE",
    "UNAPPROVED_ALTERATION",
]

# --- Canonical setup literals used by the §1.8 / §1.9 design recipes ------
CANONICAL_LESSEE_NAME = "Harborline Retail Holdings LLC"
CANONICAL_LESSEE_EMAIL = "notices@harborline.example"
CANONICAL_LESSEE_RATING = "A"

CANONICAL_LEASE = {
    "commencement_date": "2020-01-01T00:00:00Z",
    "expiration_date": "2070-01-01T00:00:00Z",
    "initial_annual_base_rent_cents": 10000000,
    "revaluation_interval_years": 5,
    "reval_collar_min_uplift_bps": 1000,
    "reval_collar_max_uplift_bps": 5000,
    "percentage_rent_rate_bps": 600,
    "percentage_rent_breakpoint_cents": 100000000,
    "permitted_use_code": "RETAIL_MIXED",
    "total_permitted_gfa_sqft": 200000,
    "improvements_value_cents": 60000000,
    "reversion_land_value_cents": 40000000,
    "reversion_standard_code": "SHELL_CONDITION",
    "security_deposit_cents": 5000000,
}

SENIOR_MORTGAGE = {
    "mortgagee_legal_name": "Keystone Senior Debt Fund",
    "notice_email": "servicing@keystone.example",
    "original_principal_cents": 3000000,
    "priority_rank": 1,
    "cure_extension_days": 30,
}
MEZZ_MORTGAGE = {
    "mortgagee_legal_name": "Bayfront Mezzanine Partners",
    "notice_email": "servicing@bayfront.example",
    "original_principal_cents": 2000000,
    "priority_rank": 2,
    "cure_extension_days": 15,
}

# Opaque acting principals pinned by the design recipes.
USER_LESSOR_ADMIN = "lessor-admin-1"
USER_ASSET_MANAGER_1 = "am-1"
USER_ASSET_MANAGER_2 = "am-2"
USER_ACCOUNTANT_1 = "acct-1"
USER_ACCOUNTANT_2 = "acct-2"
USER_ARBITRATOR_NEUTRAL = "arb-neutral-1"
USER_APPRAISER_LESSOR = "appraiser-lessor-1"
USER_APPRAISER_LESSEE = "appraiser-lessee-1"
