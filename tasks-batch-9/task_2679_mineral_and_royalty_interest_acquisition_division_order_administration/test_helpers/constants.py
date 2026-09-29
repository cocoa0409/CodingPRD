"""Business constants and canonical fixture literals for task 2679.

Every value here is fixed by the PRD text; nothing is derived at runtime.
"""

# --- Roles -----------------------------------------------------------------
ROLE_TITLE_ANALYST = "TitleAnalyst"
ROLE_ACQUISITION_MANAGER = "AcquisitionManager"
ROLE_DIVISION_ORDER_ADMIN = "DivisionOrderAdmin"
ROLE_OPERATOR = "Operator"
ROLE_ROYALTY_OWNER = "RoyaltyOwner"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = [
    ROLE_TITLE_ANALYST,
    ROLE_ACQUISITION_MANAGER,
    ROLE_DIVISION_ORDER_ADMIN,
    ROLE_OPERATOR,
    ROLE_ROYALTY_OWNER,
    ROLE_PLATFORM_ADMIN,
]

# --- Logical clock ---------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# --- Enumerations ----------------------------------------------------------
STATE_CODES = ["TX", "OK", "NM", "ND"]
ACTIVITY_TIERS = ["HIGH", "MODERATE", "LOW"]
INSTRUMENT_TYPES = ["PATENT", "DEED", "PROBATE", "ASSIGNMENT"]
CONTACT_STATUSES = ["LOCATED", "UNLOCATABLE", "DECEASED_ESTATE_OPEN"]
DEFECT_TYPES = [
    "MISSING_HEIR",
    "UNRELEASED_LEASE",
    "TAX_SALE_GAP",
    "OVERCONVEYANCE",
    "UNLOCATABLE_OWNER",
]
POOLING_ELECTIONS = ["POOLED", "NON_CONSENT", "LEASED_ROYALTY_ONLY"]
PRODUCT_CODES = ["OIL", "GAS", "NGL"]

# --- Precision -------------------------------------------------------------
ACREAGE_DP = 4
MONEY_DP = 2
RATE_DP = 6
BURDEN_DP = 4
DECIMAL_INTEREST_DP = 8

# --- Title / burden --------------------------------------------------------
BURDEN_CAP = 0.2500

# --- Valuation -------------------------------------------------------------
DISCOUNT_RATE_ANNUAL = 0.10
HORIZON_YEARS = 5
RISK_FACTOR_UNDEVELOPED = 0.45
UPSIDE_PER_NET_ACRE = 1800.00
ACTIVITY_MULTIPLIER = {"HIGH": 1.20, "MODERATE": 1.00, "LOW": 0.80}

# --- Offer / PSA -----------------------------------------------------------
MAX_COUNTER_ROUNDS = 3
PSA_WINDOW_BUFFER_DAYS = 30
PSA_TERMINATION_THRESHOLD_PCT = 0.20
DEFAULT_CURATIVE_DAYS = 45

# --- Units / decimals ------------------------------------------------------
NON_CONSENT_PENALTY_PCT = 0.30
NON_CONSENT_ELECTION_FACTOR = 0.7000

# --- Revenue ---------------------------------------------------------------
SEVERANCE_RATES = {
    "TX": {"OIL": 0.046000, "GAS": 0.075000, "NGL": 0.046000},
    "OK": {"OIL": 0.070000, "GAS": 0.070000, "NGL": 0.070000},
    "NM": {"OIL": 0.037500, "GAS": 0.037500, "NGL": 0.037500},
    "ND": {"OIL": 0.050000, "GAS": 0.065000, "NGL": 0.050000},
}

# --- Suspense / escheat ----------------------------------------------------
SUSPENSE_INTEREST_ANNUAL = 0.06
ESCHEAT_MONTHS = 36

# --- Tax statement ---------------------------------------------------------
DEPLETION_RATE = 0.15
DEPLETION_INCOME_CAP_PCT = 0.65
