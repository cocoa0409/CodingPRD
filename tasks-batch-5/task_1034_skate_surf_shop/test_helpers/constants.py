"""Domain thresholds — numeric constants from the PRD's calculations (Section 3)
and system-wide principles (Section 2)."""

# Loyalty (PRD Section 2.7)
TIER_MULTIPLIER = {"BRONZE": 1.0, "SILVER": 1.25, "GOLD": 1.5}
EVENT_MULTIPLIER = 2.0
SILVER_THRESHOLD_CENTS = 50000
GOLD_THRESHOLD_CENTS = 100000

# Trade-in / consignment offer rates (PRD Section 3.7)
CASH_RATE = 0.50
STORE_CREDIT_RATE = 0.70
CONSIGNMENT_RATE = 0.60

# Board build cost (PRD Section 3.5)
BUILD_LABOR_CENTS = 2500
BUILD_BUNDLE_DISCOUNT = 0.10

# Service ticket total (PRD Section 3.6)
TAX_RATE = 0.0725

# Rental fees (PRD Section 3.4)
LATE_FEE_PER_DAY_CENTS = 1000
SECONDS_PER_DAY = 86400

# Coach scheduling (PRD Section 2.9 / 3.3)
SETUP_BUFFER_MINUTES = 15

# Logical clock default (PRD Section 2.9)
CLOCK_DEFAULT_ISO = "2026-07-01T00:00:00Z"
