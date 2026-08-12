"""Domain thresholds and canonical money figures from PRD §3.2.1, §3.2.2, §3.3."""

# Escrow fee schedule (PRD §3.2.2)
FEE_SCHEDULE = {
    "TIER1_CAP_CENTS": 50_000_000,      # $500,000
    "TIER1_BPS": 30,
    "TIER2_CAP_CENTS": 200_000_000,     # $2,000,000
    "TIER2_BPS": 20,
    "TIER3_BPS": 10,
    "MIN_FEE_CENTS": 150_000,           # $1,500 floor
    "TRUST_SURCHARGE_CENTS": 75_000,    # $750 when requires_trust
    "FEE_CAP_CENTS": 2_500_000,         # $25,000 cap
}

# Closing proration (PRD §3.2.1)
PRORATION = {
    "DAYS_PER_YEAR": 365,
    "MONTHS_PER_YEAR": 12,
    "PARTIAL_MONTH_DAY_CUTOFF": 15,
}

# Title-search freshness window (PRD §2.4, §3.3)
SEARCH_FRESHNESS_DAYS = 30

# Logical clock startup value (PRD §2.4)
CLOCK_STARTUP = "2026-05-01T00:00:00Z"

# Canonical computation results used across tests (derivable from PRD §3.2):
CANONICAL = {
    # price 10,000,000 / annual 0 -> proration 0, fee floored at 150,000
    "DUE_LOW_PRICE": 10_150_000,
    # price 250,000,000 / annual 120,000 / DAILY close 2026-06-30
    # -> proration 60,493 (184 days), fee 500,060
    "PRORATION_DAILY_120K": 60_493,
    "FEE_TIERED_250M_120K": 500_060,
    "DUE_250M_120K": 250_560_553,
    # price 250,000,000 / annual 0 -> fee 500,000
    "FEE_TIERED_250M": 500_000,
    "DUE_250M": 250_500_000,
}
