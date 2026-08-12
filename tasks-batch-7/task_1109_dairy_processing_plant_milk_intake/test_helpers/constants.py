"""Domain thresholds and numeric constants from the PRD."""

# Lab safety thresholds (PRD §3.3)
SCC_LIMIT_CELLS_PER_ML = 750000          # release requires scc < 750000
TEMPERATURE_MAX_F = 45                   # release requires temperature_f <= 45
MIN_HOLD_TEMP_F_HTST = 161               # HTST minimum holding temperature

# Hauling deduction tiers (PRD §3.11)
TIER1_CWT = 1000
TIER2_DISCOUNT_PCT_PROVISIONAL = 80
TIER2_DISCOUNT_PCT_FINAL = 75

# Over-order premium tiers, cents per cwt (PRD §3.11)
OVER_ORDER_TIER_CENTS = {"STANDARD": 150, "PREMIUM": 250, "PROBATION": 0}

# Pool blend price tiers, cents per cwt (PRD §3.10)
CLASS_TIER_HIGH = 2400
CLASS_TIER_MID = 2100
CLASS_TIER_LOW = 1800

# Shelf-life caps in days (PRD §3.6)
MAX_SHELF_LIFE_DAYS = {
    "WHOLE_MILK": 21,
    "TWO_PERCENT": 21,
    "SKIM": 21,
    "HEAVY_CREAM": 30,
    "BUTTER": 180,
    "CONDENSED_SKIM": 270,
}

# CIP validation thresholds (PRD §3.7)
CIP_CAUSTIC_MIN_MS = 80.0
CIP_PH_MIN = 6.5
CIP_PH_MAX = 8.0
CIP_FRESHNESS_HOURS = 24

# Producer standing thresholds (PRD §3.4)
PROBATION_THRESHOLD = 2
SUSPEND_THRESHOLD = 4
REJECTION_WINDOW_DAYS = 30

# Grade A permit thresholds (PRD §3.9)
INSPECTION_PASS_SCORE = 90
PERMIT_SUSPEND_VIOLATIONS = 3
PERMIT_REVOKE_VIOLATIONS = 5

# Logical clock startup default (PRD §2.6)
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Common settlement period used across tests (May 2026)
PERIOD_START_ISO = "2026-05-01T00:00:00Z"
PERIOD_END_ISO = "2026-05-31T23:59:59Z"
POOL_MONTH = "2026-05"
ANNOUNCE_DATE_ISO = "2026-06-23T00:00:00Z"

# Default pool prices (cents)
POOL_PRICES = {
    "announced_class_i_price_cents": 2200,
    "butterfat_price_cents_per_lb": 300,
    "protein_price_cents_per_lb": 250,
    "other_solids_price_cents_per_lb": 40,
}
