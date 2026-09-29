"""Numeric constants, thresholds and canonical timestamps stated by the PRD."""

# All fifty endpoints are rooted at the API prefix "/", so no extra segment.
API_PREFIX = ""

# --- Logical clock ---------------------------------------------------------
# Before any clock call has been made the logical clock reads exactly this.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# --- Pagination ------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Seller ----------------------------------------------------------------
DEFAULT_COMMISSION_BPS = 500
MIN_COMMISSION_BPS = 0
MAX_COMMISSION_BPS = 1500

# --- Trustee sale ----------------------------------------------------------
DEFAULT_STATUTORY_MAX_POSTPONEMENTS = 3
MIN_STATUTORY_MAX_POSTPONEMENTS = 0
MAX_STATUTORY_MAX_POSTPONEMENTS = 10

# --- Lot creation ----------------------------------------------------------
DEFAULT_MIN_INCREMENT_CENTS = 500000

# --- Required deposit ------------------------------------------------------
DEPOSIT_FLOOR_CENTS = 500000
DEPOSIT_PCT = 0.05
OCCUPANCY_DEPOSIT_MULTIPLIER = {
    "OWNER_OCCUPIED": 1.50,
    "TENANT_OCCUPIED": 1.25,
    "VACANT": 1.00,
    "UNKNOWN": 1.50,
}

# --- Hold extension policy -------------------------------------------------
MAX_HOLD_EXTENSIONS = 2
HOLD_EXTENSION_DAYS = 30

# --- Late-bid extension ----------------------------------------------------
EXTENSION_TRIGGER_SECONDS = 60
EXTENSION_GRANT_SECONDS = 120
MAX_LOT_EXTENSIONS = 3

# --- Buyer premium ---------------------------------------------------------
PREMIUM_TIER_1_CEILING_CENTS = 10000000
PREMIUM_TIER_2_CEILING_CENTS = 50000000
PREMIUM_TIER_1_RATE = 0.10
PREMIUM_TIER_2_RATE = 0.08
PREMIUM_TIER_3_RATE = 0.06
OCCUPANCY_SURCHARGE_BPS = {
    "OWNER_OCCUPIED": 150,
    "TENANT_OCCUPIED": 100,
    "VACANT": 0,
    "UNKNOWN": 200,
}
TITLE_SURCHARGE_BPS = {
    "CLEAR": 0,
    "JUNIOR_LIENS": 75,
    "CLOUDED": 175,
    "UNKNOWN": 250,
}
PREMIUM_FLOOR_CENTS = 250000
PREMIUM_CEILING_CENTS = 6000000

# --- Contract price --------------------------------------------------------
POSTPONE_CARRY_BPS = 25
DEFAULT_CLOSING_WINDOW_DAYS = 21
MIN_CLOSING_WINDOW_DAYS = 1
MAX_CLOSING_WINDOW_DAYS = 90

# --- Document fee ----------------------------------------------------------
DOC_FEE_BASE_CENTS = 95000
DOC_FEE_TIER_1_FLOOR_CENTS = 25000000
DOC_FEE_TIER_2_FLOOR_CENTS = 50000000
DOC_FEE_TIER_1_DISCOUNT = 0.25
DOC_FEE_TIER_2_DISCOUNT = 0.40

# --- Settlement split ------------------------------------------------------
MARKETING_RECOVERY_BPS = 35
TITLE_SERVICE_FEE_CENTS = 45000

# --- Forfeiture split ------------------------------------------------------
FORFEIT_SELLER_BPS = 6000

# --- Bidder risk score -----------------------------------------------------
IDENTITY_PENALTY_POINTS = 25
EXCLUSION_PENALTY_POINTS = 20
FALLOUT_PENALTY_POINTS = 15
DEPOSIT_PENALTY_POINTS = 10
RISK_SCORE_CAP = 100
ELIGIBILITY_MAX_SCORE = 40
BARRING_FALLOUT_THRESHOLD = 2

# --- Interval arithmetic ---------------------------------------------------
COUNTY_BUFFER_MINUTES = 30

# --- Second-chance offers --------------------------------------------------
OFFER_DEFAULT_EXPIRY_DAYS = 3

# --- Canonical scenario geography and timeline ----------------------------
# The recurring county pair used by the scenarios in this suite.
COUNTY_PRIMARY = "CA-ALAMEDA"
COUNTY_SECONDARY = "CA-CONTRA-COSTA"
STATE_CODE = "CA"

# A quiet clock instant well before every auction window below.
CLOCK_SETUP = "2026-08-05T00:00:00Z"

# The canonical event window and the canonical lot window inside it.
EVENT_START = "2026-09-15T17:00:00Z"
EVENT_END = "2026-09-15T19:00:00Z"
LOT_WINDOW_START = "2026-09-15T17:00:00Z"
LOT_WINDOW_END = "2026-09-15T18:00:00Z"

# Clock instants for the recurring stages of a lot's life.
CLOCK_EVENT_OPEN = "2026-09-15T17:05:00Z"
CLOCK_BIDDING = "2026-09-15T17:10:00Z"
CLOCK_LOT_CLOSE = "2026-09-15T18:05:00Z"
CLOCK_CONTRACT = "2026-09-15T18:10:00Z"

# Two distinct AuctionOps operators: the four-eyes rule forbids the operator
# who closed a lot from executing that lot's purchase contract.
OPS_CLOSER = "ops-closer-1"
OPS_CONTRACT = "ops-contract-2"
