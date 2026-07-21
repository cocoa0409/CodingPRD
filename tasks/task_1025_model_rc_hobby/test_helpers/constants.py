"""Domain thresholds and pricing constants from the PRD calculations."""

# Order pricing (PRD 3.4)
DISCOUNT_PCT = {"BRONZE": 0, "SILVER": 5, "GOLD": 10}
HAZMAT_SURCHARGE_CENTS = 500

# Loyalty points multiplier x100 (PRD 3.4)
MULT_X100 = {"BRONZE": 100, "SILVER": 150, "GOLD": 200}

# Loyalty tier thresholds (PRD 3.1) — inclusive lower bound
SILVER_THRESHOLD_CENTS = 50000
GOLD_THRESHOLD_CENTS = 200000

# Service pricing (PRD 3.5)
SERVICE_LABOR_RATE_CENTS = 6000
REWORK_SURCHARGE_CENTS = 2500

# Service bench scheduling buffer (PRD 2.8)
SERVICE_BUFFER_MINUTES = 30

# Logical clock (PRD 2.8) — server startup default
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"

# Convenient time windows that bracket the default clock so most chains
# need no explicit clock-set.
OPEN_WINDOW_START = "2026-07-01T00:00:00Z"
OPEN_WINDOW_END = "2026-12-31T00:00:00Z"
