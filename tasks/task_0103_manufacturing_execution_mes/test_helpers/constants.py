"""Domain thresholds — numeric constants from the MES PRD calculations (§3.3, §3.10)."""

# OEE quality floor: oee_quality at or below this flags the machine (§3.3).
QUALITY_FLOOR = 0.95

# Labor rate used by the cost summary (§3.10): 2 cents per labor second.
LABOR_RATE_CENTS_PER_SEC = 2

# OEE ratios are rounded to 4 decimal places, round-half-up (§2.7).
OEE_DECIMAL_PLACES = 4

# Default planned production seconds per shift for fixtures (OEE availability denominator).
DEFAULT_PLANNED_PRODUCTION_SECS = 28800
