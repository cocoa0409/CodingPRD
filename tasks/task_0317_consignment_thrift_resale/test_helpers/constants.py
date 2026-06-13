"""Domain thresholds — numeric constants from the PRD's calculations.

All monetary values are integer cents.
"""

# Markdown pricing
SECONDS_PER_DAY = 86400
DEFAULT_BASE_FLOOR_PCT = 0.30

# Split-base processing fee (flat, per line, frozen at sale time)
PROCESSING_FEE_CENTS = 150

# Store-credit bonus tiers (on the line's consignor_proceeds_cents)
BONUS_TIER1_MIN_CENTS = 2000      # proceeds >= $20 -> 10% bonus
BONUS_TIER1_PCT = 0.10
BONUS_TIER2_MIN_CENTS = 10000     # proceeds >= $100 -> 20% bonus
BONUS_TIER2_PCT = 0.20

# Donation tax-receipt valuation (DONATED disposition only, floored)
DONATION_VALUATION_PCT = 0.25

# Pagination bounds
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

THRESHOLDS = {
    "SECONDS_PER_DAY": SECONDS_PER_DAY,
    "PROCESSING_FEE_CENTS": PROCESSING_FEE_CENTS,
    "BONUS_TIER1_MIN_CENTS": BONUS_TIER1_MIN_CENTS,
    "BONUS_TIER1_PCT": BONUS_TIER1_PCT,
    "BONUS_TIER2_MIN_CENTS": BONUS_TIER2_MIN_CENTS,
    "BONUS_TIER2_PCT": BONUS_TIER2_PCT,
    "DONATION_VALUATION_PCT": DONATION_VALUATION_PCT,
    "DEFAULT_BASE_FLOOR_PCT": DEFAULT_BASE_FLOOR_PCT,
}

# A non-existent but well-formed UUID for not-found probes (the framework also
# exports NON_EXISTENT_UUID; this literal mirrors the design indices' value).
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
