"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# Default threshold: missed_payment_count required to permit declare-default (PRD §3.3).
DEFAULT_THRESHOLD = 3

# Late-fee calculation constants (PRD §3.3).
LATE_FEE_PCT = 0.05
LATE_FEE_MIN_CENTS = 2500

# Canonical rate card "2026-Q2" values used across the test suite (PRD §3.1).
RATE_CARD_2026_Q2 = {
    "name": "2026-Q2",
    "tier_1_min_fico": 740,
    "tier_2_min_fico": 680,
    "tier_3_min_fico": 620,
    "tier_1_apr": 0.0399,
    "tier_2_apr": 0.0599,
    "tier_3_apr": 0.0899,
    "tier_4_apr": 0.1499,
    "lease_money_factor": 0.00125,
    "default_rate_apr": 0.2499,
    "lease_tax_rate": 0.0725,
}

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
