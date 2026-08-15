"""Domain thresholds — numeric constants from the PRD calculation rules."""

# Entitlement (PRD §3.2): block hours a full (1/1) share carries per contract year.
FULL_SHARE_HOURS = 800

# Notice-tier thresholds in hours (PRD §3.3).
TIER_72H_HOURS = 72
TIER_7D_HOURS = 168

# Peak-day surcharge in basis points (PRD §3.6: "adds 15 percent of that base").
PEAK_SURCHARGE_BP = 1500

# Exit buyout formula constants (PRD §3.9).
MARKET_VALUE_BP = 8200
EARLY_EXIT_BP = 2000
MIN_HOLD_YEARS = 3

# Invoice aging: issued invoices roll to PAST_DUE once thirty days pass (PRD §3.6).
PAST_DUE_DAYS = 30

# Listing expiry: LISTED listings expire one hundred eighty days after creation (PRD §2.4).
LISTING_EXPIRY_DAYS = 180

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Standard fleet class fixtures used across tests.
CLASS_SPECS = {
    "LIGHT": {"hourly_rate_cents": 300000, "monthly_fee_base_cents": 1500000, "seats": 6},
    "MID": {"hourly_rate_cents": 450000, "monthly_fee_base_cents": 2500000, "seats": 8},
    "SUPER_MID": {"hourly_rate_cents": 600000, "monthly_fee_base_cents": 3000000, "seats": 10},
    "HEAVY": {"hourly_rate_cents": 900000, "monthly_fee_base_cents": 4000000, "seats": 14},
}
DEFAULT_MULTIPLIER_BP = 12500
