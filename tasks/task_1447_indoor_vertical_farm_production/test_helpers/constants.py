"""Domain thresholds — numeric constants named in the PRD (§2.4, §3.3-§3.8)."""

# Logical farm clock (PRD §2.4)
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Grow batch schedule (PRD §3.3)
STRESS_EXTENSION_CAP = 5
HARVEST_READY_EARLY_HOURS = 48
GERMINATION_REPLANT_THRESHOLD = 75.0

# Yield tier boundaries (PRD §3.3)
YIELD_TIER_1_MIN = 95.0   # >= 95.0 -> factor 1.00
YIELD_TIER_2_MIN = 85.0   # >= 85.0 -> factor 0.90
YIELD_TIER_3_MIN = 75.0   # >= 75.0 -> factor 0.75; below -> 0.50 + replant flag

# Sanitation schedule (PRD §3.2, §3.4)
SANITATION_INTERVAL_HOURS = 168
SANITATION_BUFFER_HOURS = 4
MIN_CYCLE_HOURS = 2
MAX_CYCLE_HOURS = 12
SANITATION_EARLY_START_MINUTES = 30
FOOD_SAFETY_RECENCY_HOURS = 72

# Energy cost per pound (PRD §3.8)
FIXTURE_KW_PER_TOWER = 0.6
ENERGY_RATE_CENTS_PER_KWH = 11
DEMAND_TIER1_LIMIT_KW = 500
DEMAND_RATE_T1_CENTS_PER_KW = 900
DEMAND_RATE_T2_CENTS_PER_KW = 1400

# Contract settlement (PRD §3.5)
ESCALATION_MULTIPLIER = 1.25
DOCK_MAX_SHIPMENTS_PER_DAY = 3

# Harvest labor cost (PRD §3.7)
PRODUCTIVITY_LEAFY_GREEN = 60
PRODUCTIVITY_HERB = 40
PRODUCTIVITY_FRUITING = 25
SHIFT_LENGTH_HOURS = 8
OT_MULTIPLIER = 1.5
REGULAR_HOURS_PER_WEEK = 40.0
WEEKLY_HOURS_HARD_CAP = 48.0

# Standard fixture data shared across tests
DEFAULT_KALE_RECIPE = {
    "light_hours_per_day": 16,
    "light_ppfd_umol": 600,
    "ec_target_ms": 1.8,
    "ph_target": 5.8,
    "temp_day_c": 22,
    "temp_night_c": 18,
    "humidity_pct": 65,
    "co2_ppm": 900,
    "days_to_harvest": 21,
    "expected_yield_lb_per_tower": 12.5,
}

DEFAULT_BASIL_RECIPE = {
    "light_hours_per_day": 14,
    "light_ppfd_umol": 500,
    "ec_target_ms": 1.6,
    "ph_target": 6.0,
    "temp_day_c": 23,
    "temp_night_c": 19,
    "humidity_pct": 60,
    "co2_ppm": 800,
    "days_to_harvest": 21,
    "expected_yield_lb_per_tower": 10.0,
}

# Standard logical-clock waypoints used by the composite fixtures
SEED_CLOCK = "2026-08-03T06:00:00Z"
SANITATION_CYCLE_START = "2026-08-22T01:00:00Z"
SANITATION_CYCLE_END = "2026-08-22T03:00:00Z"
SANITATION_PASS_CLOCK = "2026-08-22T03:30:00Z"
HARVEST_READY_CLOCK = "2026-08-22T06:00:00Z"
HARVEST_CLOCK = "2026-08-24T06:30:00Z"
SHIP_DATE = "2026-08-24"
SHIP_WINDOW_START = "2026-08-24T08:00:00Z"
SHIP_WINDOW_END = "2026-08-24T20:00:00Z"

# Operator identities used by segregation-of-duties scenarios
HARVESTER_USER_ID = "grower-7"
QA_USER_ID = "qa-1"
QA_USER_ID_2 = "qa-2"
SANITATION_USER_1 = "san-1"
SANITATION_USER_2 = "san-2"
