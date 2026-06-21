"""Domain thresholds — numeric constants from PRD calculations."""

# Labor rate used across per-piece subtotal, estimate, and final invoice.
LABOR_RATE_CENTS_PER_HOUR = 6500

# Rush surcharge tiering (estimate_total).
RUSH_TIER1_CENTS = 50000
RUSH_PCT_LOW = 0.15
RUSH_PCT_HIGH = 0.30

# Turnaround band (approval).
STANDARD_BASE_DAYS = 3
HOURS_PER_DAY = 8
RUSH_COMPRESS = 0.5
RUSH_FLOOR_DAYS = 2

# Deposit gate (approval).
DEPOSIT_PCT = 0.30

# Warranty coverage window in whole days (inclusive at boundary).
WARRANTY_DAYS = 90
