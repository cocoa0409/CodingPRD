"""Domain thresholds — numeric constants from PRD calculations (§2.8, §3.5, §3.7, §3.8)."""

# Bacteria exceedance assessment (§3.5)
BACTERIA_THRESHOLDS = {
    "ADVISORY_THRESHOLD_MPN": 35,
    "CLOSURE_THRESHOLD_MPN": 104,
    "GEOMEAN_WINDOW_DAYS": 30,
}

# Parking fee (§3.7)
PARKING_FEE = {
    "WEEKDAY_MULT": 1.0,
    "WEEKEND_MULT": 1.5,
    "OVERSIZED_DAILY_SURCHARGE_CENTS": 2000,
    "RESIDENT_DISCOUNT_RATE": 0.5,
    "SEASON_BASE_RESIDENT_CENTS": 15000,
    "SEASON_BASE_NONRESIDENT_CENTS": 30000,
    "OVERSIZED_SEASON_SURCHARGE_CENTS": 5000,
}

# Seasonal parking revenue (§3.8)
TOWN_SURCHARGE_RATE = 0.085

# Pagination defaults (§2.3)
PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}

# Logical-clock startup default (§2.9)
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"
