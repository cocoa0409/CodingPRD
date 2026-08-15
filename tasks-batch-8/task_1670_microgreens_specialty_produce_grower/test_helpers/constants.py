"""Domain thresholds and default values from PRD §2.5, §2.7, §3."""

# PRD §3.2 — germination clearance boundary (inclusive).
GERMINATION_PASS_THRESHOLD = 0.85

# PRD §3.4 — sanitation wash-water inclusive band (parts per million).
WASH_WATER_PPM_MIN = 50
WASH_WATER_PPM_MAX = 200

# PRD §3.7 — POST_HARVEST_PRICING spoilage-credit constants.
PLAN_CAP_THRESHOLD = 0.70       # harvest ratio at/above which no plan cap applies
PLAN_CAP_FACTOR = 0.85          # cap factor when the harvest falls short
OVERWEIGHT_ALLOWANCE = 1.10     # variety overweight ratio allowance
MAX_PRICE_REDUCTION = 0.25      # the overweight excess never counts more than this

# PRD §3.1 — adoption thresholds.
ADOPT_MIN_FLAVOR_SCORE = 6.0
ADOPT_MIN_YIELD_SCORE = 5.0

# PRD §2.5 — logical clock startup value.
LOGICAL_CLOCK_START = "2026-08-01T00:00:00Z"
LOGICAL_CLOCK_START_DATE = "2026-08-01"

# A Monday used as the effective week start throughout the scenarios.
WEEK_START_MONDAY = "2026-08-03"
CUTOFF_WEDNESDAY = 2            # day-of-week index, 0=Mon .. 6=Sun

TEST_DEFAULTS = {
    "VARIETY_PRICE_CENTS_PER_KG": 800,
    "VARIETY_DAYS_TO_HARVEST": 10,
    "VARIETY_YIELD_GRAMS_PER_TRAY": 20000,
    "VARIETY_MIN_ORDER_GRAMS": 250,
    "SEEDS_ON_HAND_GRAMS": 500,
    "PLANNED_TRAY_COUNT": 2,
    "SEED_GRAMS_REQUIRED": 10,
    "MIN_STOP_SUBTOTAL_CENTS": 100,
    "ROUTE_SERVICE_DATE": "2026-08-14",
}
