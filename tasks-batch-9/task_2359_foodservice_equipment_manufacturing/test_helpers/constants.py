"""Domain constants and thresholds declared by the PRD.

Every value here is stated verbatim somewhere in the PRD; the tests import
these instead of re-typing magic numbers.
"""

# --------------------------------------------------------------------------
# Clock (PRD §2.5)
# --------------------------------------------------------------------------

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Certification (PRD §3.1)
# --------------------------------------------------------------------------

LISTING_TERM_DAYS = 365
MAX_LISTING_REVISIONS = 3

REQUIRED_SCOPE_ORDER = ["SANITATION", "GAS", "ELECTRICAL"]

AGENCY_ACCREDITED_SCOPES = {
    "AGENCY_ALPHA": ["SANITATION"],
    "AGENCY_BETA": ["GAS", "ELECTRICAL"],
    "AGENCY_GAMMA": ["SANITATION", "GAS", "ELECTRICAL"],
}

# --------------------------------------------------------------------------
# Configuration pricing (PRD §3.3)
# --------------------------------------------------------------------------

OPTION_UPLIFT_PCT = {
    "SPLIT_TANK": 0.075,
    "HIGH_ALT": 0.0325,
    "LEFT_HINGE": 0.015,
    "ENERGY_SAVER": 0.0425,
}

# Fixed application order for the option uplifts.
OPTION_UPLIFT_ORDER = ["SPLIT_TANK", "HIGH_ALT", "LEFT_HINGE", "ENERGY_SAVER"]

CONTROLS_UPLIFT_CENTS = {
    "STANDARD_DIAL": 0,
    "TOUCH_PRO": 185000,
    "CONNECT_PLUS": 340000,
}

BRANDING_KIT_CENTS = {
    "NONE": 0,
    "LOGO_BADGE": 42000,
    "FULL_WRAP": 156000,
}

# (minimum contracted unit volume, discount rate) ordered from the highest
# tier downwards.
VOLUME_DISCOUNT_TIERS = [
    (500, 0.12),
    (200, 0.08),
    (50, 0.04),
]
NO_VOLUME_DISCOUNT_PCT = 0.0

# --------------------------------------------------------------------------
# Performance validation (PRD §3.4)
# --------------------------------------------------------------------------

CERTIFIED_WINDOW_SIZE = 3
MIN_TEST_RUNS = 3
RETEST_LIMIT = 3
HOLD_TEMP_TOLERANCE_C = 2.0

# --------------------------------------------------------------------------
# Programmes and site orders (PRD §3.6)
# --------------------------------------------------------------------------

TRANSIT_DAYS = 7
AT_RISK_GRACE_DAYS = 3

# --------------------------------------------------------------------------
# Production slots (PRD §3.7)
# --------------------------------------------------------------------------

CHANGEOVER_BUFFER_HOURS = 12

# --------------------------------------------------------------------------
# Connected fleet (PRD §3.8)
# --------------------------------------------------------------------------

HEALTH_SCORE_BASE = 100
HEALTH_FAULT_WEIGHT = 7
HEALTH_MISSED_HEARTBEAT_WEIGHT = 3
HEALTH_REFERENCE_FIRMWARE_BONUS = 5
HEALTH_SCORE_MIN = 0
HEALTH_SCORE_MAX = 100
REFERENCE_FIRMWARE_VERSION = "1.0.0"

MAX_CONCURRENT_CAMPAIGNS_PER_MODEL = 2
COHORT_SIZE = {"CANARY": 3, "BROAD": 5}
MIN_CAMPAIGN_SUCCESS_RATE = 0.80

# --------------------------------------------------------------------------
# Service partners, technicians and warranty (PRD §3.9)
# --------------------------------------------------------------------------

MIN_TRAINING_HOURS = 24
TECHNICIAN_PASS_SCORE = 80
CERTIFICATION_TERM_DAYS = 730
MIN_CERTIFIED_TECHNICIANS_PER_MODEL = 2

COVERAGE_TERM_DAYS = {"BASE": 365, "EXTENDED_PLUS": 730}
RESERVE_INITIAL_CENTS = {"BASE": 250000, "EXTENDED_PLUS": 600000}
EXTENSION_TERM_DAYS = 365
EXTENSION_RESERVE_CENTS = 300000
GRACE_PERIOD_DAYS = 30

PARTS_CAP_CENTS = 180000
LABOR_RATE_CENTS_PER_HOUR = {"BASE": 9000, "EXTENDED_PLUS": 11000}

# (inclusive lower bound on pre-claim reserve utilisation, coinsurance rate)
COINSURANCE_BANDS = [
    (0.85, 0.25),
    (0.60, 0.10),
    (0.00, 0.00),
]

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
