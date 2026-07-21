"""Domain thresholds — numeric constants from PRD calculations and rules."""

# Occupancy band multipliers and boundaries (PRD §3.5).
BAND = {
    "SMALL_MAX_PAX": 5,      # SMALL when pax < 6
    "LARGE_MIN_PAX": 12,     # LARGE when pax >= 12
    "SMALL_MULT": 1.20,
    "STANDARD_MULT": 1.00,
    "LARGE_MULT": 0.90,
}

# Fee / premium rates (PRD §3.5).
SERVICE_FEE_RATE = 0.0725
INSURANCE_PREMIUM_RATE = 0.06

# Cancellation penalty tiers by whole days before start_date (PRD §3.8).
CANCEL_TIER = {
    "TIER_60_PCT": 0.10,   # >= 60 days
    "TIER_30_PCT": 0.25,   # 30..59 days
    "TIER_15_PCT": 0.50,   # 15..29 days
    "TIER_0_PCT": 1.00,    # < 15 days
}

# Voucher / scheduling constants.
MEAL_VOUCHER_CENTS = 2500
DOT_MAX_DRIVE_HOURS_PER_DAY = 10
TURNAROUND_BUFFER_DAYS = 1

# Default deposit when omitted (PRD §3.1).
DEFAULT_DEPOSIT_PER_PERSON_CENTS = 20000

# Logical clock default before any set (PRD §2.9).
DEFAULT_CLOCK_UTC = "2026-07-01T00:00:00Z"

TEST_DEFAULTS = {
    "BASE_PRICE": 100000,
    "DEPOSIT": 20000,
    "COACH_DAY_RATE": 50000,
    "DRIVER_DAY_RATE": 40000,
    "GUIDE_DAY_RATE": 30000,
}
