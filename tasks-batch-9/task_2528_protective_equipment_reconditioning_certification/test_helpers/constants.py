"""Domain thresholds and literals stated by the PRD.

Every value here is quoted by the PRD prose; nothing is inferred.
"""

# --------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# --------------------------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Service age (PRD §3.4)
# --------------------------------------------------------------------------
DAYS_PER_SERVICE_YEAR = 365

# --------------------------------------------------------------------------
# Severity index (PRD §3.5)
# --------------------------------------------------------------------------
SITE_WEIGHT_FRONT = 0.5
SITE_WEIGHT_SIDE = 0.3
SITE_WEIGHT_CROWN = 0.2
SITE_CONTRIBUTION_CAP = 150.0
CONDITION_MULTIPLIER = {"AMBIENT": 1.00, "HOT": 1.15, "COLD": 1.08}
MATERIAL_OFFSET = {"POLYCARBONATE": 0, "ABS": 25}

# --------------------------------------------------------------------------
# Settlement money (PRD §3.9)
# --------------------------------------------------------------------------
BASE_SERVICE_CENTS = 8996
TIER_MULTIPLIER = {"STANDARD": 1.00, "SEASONAL_CONTRACT": 1.00, "PRIORITY_RUSH": 1.35}
CONDEMN_HANDLING_CENTS = 2500
REPAIR_LABOR_CENTS = 4500
DISCOUNT_TIER_1_FLOOR = 10000
DISCOUNT_TIER_2_FLOOR = 100000
DISCOUNT_RATE_TIER_0 = 0.000
DISCOUNT_RATE_TIER_1 = 0.125
DISCOUNT_RATE_TIER_2 = 0.150
COMPLIANCE_SURCHARGE_RATE = 0.02

# --------------------------------------------------------------------------
# Turnaround commitment (PRD §3.9)
# --------------------------------------------------------------------------
TIER_BASE_DAYS = {"STANDARD": 30, "SEASONAL_CONTRACT": 30, "PRIORITY_RUSH": 10}
UNITS_PER_BATCH_DAY = 25
SEASON_BUFFER_DAYS = 7

# --------------------------------------------------------------------------
# Label traceability (PRD §3.7)
# --------------------------------------------------------------------------
LABEL_PREFIX = "RCP"
SEQUENCE_PAD_WIDTH = 3
LABEL_FRESHNESS_DAYS = 14

# --------------------------------------------------------------------------
# Liability, loaner recall and repair verification (PRD §3.1, §3.6)
# --------------------------------------------------------------------------
REQUIRED_WAIVER_VERSION = "2026.1"
STALE_WAIVER_VERSION = "2025.2"
LOANER_RECALL_GRACE_DAYS = 14
MAX_VERIFICATION_ATTEMPTS = 2

# --------------------------------------------------------------------------
# Bench defaults (PRD §3.2)
# --------------------------------------------------------------------------
DEFAULT_COOLDOWN_MINUTES = 45

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Reference ModelSpec used across the suite (PRD §3.2 bands)
# --------------------------------------------------------------------------
TEST_DEFAULTS = {
    "MODEL_CODE": "SF-2026",
    "MANUFACTURER": "Riddell",
    "STANDARD_CODE": "ND002",
    "MAX_SERVICE_LIFE_YEARS": 10,
    "WARRANTY_YEARS": 5,
    "RECORD_RETENTION_YEARS": 3,
    "PASS_SI_MAX": 300.0,
    "REPAIR_SI_MAX": 360.0,
    "MAX_RETEST_COUNT": 3,
    "MANUFACTURE_DATE": "2018-09-15T00:00:00Z",
    "SEASON_START_DATE": "2026-08-25T00:00:00Z",
    "SEASON_END_DATE": "2026-11-20T00:00:00Z",
    "SHELL_MEASUREMENT_PASS": 1.50,
    "SHELL_REPLACE_THRESHOLD": 4.0,
    "SHELL_FAIL_THRESHOLD": 6.0,
    "BENCH_DAILY_SESSION_QUOTA": 6,
    "BENCH_CALIBRATION_VALID_UNTIL": "2026-12-31T00:00:00Z",
    "PART_UNIT_PRICE_CENTS": 4500,
}
