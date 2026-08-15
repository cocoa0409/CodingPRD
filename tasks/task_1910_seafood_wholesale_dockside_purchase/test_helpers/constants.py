"""Domain thresholds and tariff constants from the PRD (§3.2, §3.4, §3.7)."""

# Logical clock startup reading (PRD §2.6).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Default landing window used by fixtures (PRD §3.3).
DEFAULT_LANDING_START = "2026-08-01T06:00:00Z"
DEFAULT_LANDING_END = "2026-08-01T10:00:00Z"
DEFAULT_QUOTE_DATE = "2026-08-01"
DEFAULT_DELIVERY_DATE = "2026-08-05"

# Volatility guard threshold in percent (PRD §3.2).
VOLATILITY_THRESHOLD_PCT = 10.00

# Air freight pooled capacity per (flight_number, flight_date) in kg (PRD §3.7).
FLIGHT_CAPACITY_KG = 1000

# Freight tariff constants (PRD §3.7).
DIM_KG_PER_M3 = 167
FREIGHT_BASE_CENTS = {"AIR": 5000, "TRUCK": 2500}
FREIGHT_PER_KG_CENTS = {"AIR": 320, "TRUCK": 140}
FREIGHT_DISCOUNT_TIER_CENTS = 10000
FREIGHT_DISCOUNT_PCT = 0.05
FREIGHT_FUEL_PCT = 0.12
FREIGHT_MIN_CHARGE_CENTS = 4000

# Yield-processing factors (PRD §3.4).
GRADE_CONDITION_FACTOR = {"GRADE_A": 1.00, "GRADE_B": 0.97, "GRADE_C": 0.92}
PROCESSING_FACTOR = {"WHOLE": 1.00, "FILLETED": 0.85}

# Re-grade hard cap on a dock ticket (PRD §3.4).
REGRADE_CAP = 2
