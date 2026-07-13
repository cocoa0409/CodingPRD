"""Domain thresholds — numeric constants from the PRD calculation and booking rules."""

THRESHOLDS = {
    "DAYS_PER_MONTH": 30,          # §3.6 full-month divisor for proration
    "TAX_EXEMPT_THRESHOLD_DAYS": 30,  # §3.7 stays >= 30 nights are tax-exempt
    "MIN_LEASE_TERM_DAYS": 30,     # §3.3 minimum lease term
    "TURNOVER_BUFFER_DAYS": 1,     # §3.3 required unit separation between stays
}

# Default rate plan used across most fixtures (monthly 300000, utility 15000,
# cleaning 12000, tax 1200 bps == 12%).
TEST_DEFAULTS = {
    "MONTHLY_RATE_CENTS": 300_000,
    "UTILITY_MONTHLY_CENTS": 15_000,
    "CLEANING_FEE_CENTS": 12_000,
    "OCCUPANCY_TAX_RATE_BPS": 1_200,
    "NEGOTIATED_MONTHLY_RATE_CENTS": 280_000,
}

# A well-formed UUID that is guaranteed not to resolve to any created entity.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
