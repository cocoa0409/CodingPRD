"""Domain thresholds and literal constants stated by the PRD."""

# --- Logical clock -------------------------------------------------------
# The clock's startup value; every stamp reads it until the clock is moved.
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"
CLOCK_STARTUP_UTC_STAMPED = "2026-08-01T00:00:00.000Z"

# --- Cube and density ----------------------------------------------------
CUBIC_INCHES_PER_CUBIC_FOOT = 1728
CUBE_UNIT_DECIMALS = 3
CUBE_LINE_DECIMALS = 2
DENSITY_DECIMALS = 2

# --- The eighteen recognized classification codes ------------------------
CLASS_CODES = [
    50, 55, 60, 65, 70, 77.5, 85, 92.5, 100,
    110, 125, 150, 175, 200, 250, 300, 400, 500,
]

# --- Characteristic class floors ----------------------------------------
HANDLING_FLOOR = {"STANDARD": 0, "FRAGILE": 100, "HAZMAT": 125, "OVERLENGTH": 110}
STOWABILITY_FLOOR = {"STACKABLE": 0, "NON_STACKABLE": 92.5, "HAZ_SEGREGATED": 125}
LIABILITY_FLOOR = {"LOW": 0, "MEDIUM": 70, "HIGH": 100}

# --- Weight-break factors, descending threshold order -------------------
WEIGHT_BREAK_FACTORS = [
    (5000, 0.78),
    (2000, 0.88),
    (1000, 1.00),
    (500, 1.15),
    (0, 1.30),
]

# --- Volume-discount tiers on undiscounted annual gross, in cents -------
VOLUME_TIER_DISCOUNTS = [
    (5_000_000, 0.12),
    (2_000_000, 0.08),
    (500_000, 0.04),
    (0, 0.00),
]
MIGRATE_THRESHOLD = 0.05
HOLD_THRESHOLD = -0.05

# --- Inspection fees frozen at issuance ---------------------------------
RECLASS_FEE_CENTS = 4500
REWEIGH_FEE_CENTS = 2500

# --- Evidence floors ----------------------------------------------------
MIN_EVIDENCE_BUNDLE = 1
MIN_FINDING_PHOTOS = 2
MIN_DISPUTE_DOCS = 1

# --- The variance gate --------------------------------------------------
REWEIGH_VARIANCE_PCT = 2.00
REWEIGH_MIN_ABS_LB = 10

# --- Liability indices, tiers and windows -------------------------------
ROLLING_WINDOW_DAYS = 90
DECAY_PER_DAY = 0.01
DECAY_FLOOR = 0.25
UPHELD_WEIGHT = 1.0
PARTIAL_WEIGHT = 0.5
TIER_1_MIN = 1.00
TIER_2_MIN = 3.00
TIER_3_MIN = 6.00
BASE_DISPUTE_WINDOW_DAYS = 30
TIER_WINDOW_STEP_DAYS = 5
DISPUTE_WINDOW_BY_TIER = {"TIER_0": 30, "TIER_1": 25, "TIER_2": 20, "TIER_3": 15}

# --- Education ----------------------------------------------------------
DEFAULT_EDUCATION_STRIKE_INTERVAL = 3

# --- Dispute rounds and supplements -------------------------------------
SUPPLEMENT_EXTENSION_DAYS = 7
MAX_SUPPLEMENT_REQUESTS = 2
MAX_DISPUTE_ROUNDS = 3

# --- Credit waterfall ---------------------------------------------------
INTEREST_RATE_PER_ROUND = 0.005
INTEREST_CAP_CENTS = 250

# --- Repricing runs -----------------------------------------------------
REPRICING_BUFFER_HOURS = 24

# --- Terminals ----------------------------------------------------------
DEFAULT_CALIBRATION_INTERVAL_CAPTURES = 250

# --- Pagination ---------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# --- Shared test defaults used across fixtures --------------------------
TEST_DEFAULTS = {
    "TERMINAL_CODE": "TRM1",
    "TERMINAL_NAME": "Chicago Dock",
    "ACCOUNT_CODE": "ACME",
    "CUSTOMER_NAME": "Acme Mfg",
    "TARIFF_CODE": "NMFC-2026A",
    "TARIFF_EFFECTIVE_AT": "2026-01-01T00:00:00Z",
    "NMFC_ITEM": "156600",
    "COMMODITY_DESCRIPTION": "Machine parts, boxed",
    "BASE_RATE_PER_CWT_CENTS": 4200,
    "DISCOUNT_PCT": 0.35,
    "MIN_CHARGE_CENTS": 12500,
    "PICKUP_AT": "2026-01-10T08:00:00Z",
    "WORKING_CLOCK": "2026-01-10T08:00:00Z",
}

# The thirteen-row bracket table used by every scenario in this suite:
# strictly descending by min_density_pcf and terminating at exactly 0.
STANDARD_DENSITY_BREAKS = [
    {"min_density_pcf": 30, "class_code": 60},
    {"min_density_pcf": 22.5, "class_code": 65},
    {"min_density_pcf": 15, "class_code": 70},
    {"min_density_pcf": 13.5, "class_code": 85},
    {"min_density_pcf": 12, "class_code": 92.5},
    {"min_density_pcf": 10.5, "class_code": 100},
    {"min_density_pcf": 9, "class_code": 110},
    {"min_density_pcf": 8, "class_code": 125},
    {"min_density_pcf": 6, "class_code": 150},
    {"min_density_pcf": 4, "class_code": 175},
    {"min_density_pcf": 2, "class_code": 250},
    {"min_density_pcf": 1, "class_code": 300},
    {"min_density_pcf": 0, "class_code": 400},
]

# A short but well-formed bracket table for cases that only need publication.
MINIMAL_DENSITY_BREAKS = [
    {"min_density_pcf": 15, "class_code": 70},
    {"min_density_pcf": 0, "class_code": 400},
]
