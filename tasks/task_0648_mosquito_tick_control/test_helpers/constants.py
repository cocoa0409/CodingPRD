"""Domain thresholds — numeric constants from PRD calculations."""

# Per-zone application rate, cents per 1000 sqft, keyed by zone_type (PRD §3.6).
ZONE_RATE_CENTS_PER_1000_SQFT = {
    "TURF": 120,
    "PERIMETER": 200,
    "WATER_FEATURE": 350,
    "WOODLINE": 280,
}

# Tiered flat area surcharge on total_treatable_sqft (PRD §3.6).
AREA_TIER_BREAKS_SQFT = [5000, 10000, 20000]
AREA_TIER_SURCHARGE_CENTS = [0, 1500, 3500, 6000]

# Special-event premium flat surcharge (PRD §3.6).
SPECIAL_EVENT_SURCHARGE_CENTS = 4000

# Seasonal charge constants (PRD §3.6).
TICK_BARRIER_SEASON_CENTS = 8000
VOLUME_DISCOUNT_TIER_COUNTS = [6, 10]   # >=6 -> 7%, >=10 -> 12%
VOLUME_DISCOUNT_BPS = [0, 700, 1200]

# Re-scheduling cap (PRD §3.3): a visit may be rescheduled at most 3 times.
MAX_RESCHEDULE_COUNT = 3

# Pre-renewal season shift (PRD §3.9).
RENEWAL_SHIFT_DAYS = 365

TEST_DEFAULTS = {
    "PER_VISIT_PRICE_CENTS": 5000,
    "SEASONAL_PRICE_CENTS": 30000,
    "VISIT_INTERVAL_DAYS": 21,
    "RETREAT_GUARANTEE_DAYS": 7,
}
