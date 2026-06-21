"""Domain thresholds and test defaults derived from the PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Threshold constants stated in the PRD.
# §3.7: PASS when age is at least 21 years — the legal minimum for age-restricted goods.
MIN_AGE_YEARS = 21

# §3.1: store cold_chain_hold_minutes defaults to 120 (two hours).
DEFAULT_COLD_CHAIN_HOLD_MINUTES = 120

# §3.1: picker window_cooldown_minutes defaults to 15.
DEFAULT_WINDOW_COOLDOWN_MINUTES = 15

# Pagination defaults (§2.3).
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

THRESHOLDS = {
    "MIN_AGE_YEARS": MIN_AGE_YEARS,
    "DEFAULT_COLD_CHAIN_HOLD_MINUTES": DEFAULT_COLD_CHAIN_HOLD_MINUTES,
    "DEFAULT_WINDOW_COOLDOWN_MINUTES": DEFAULT_WINDOW_COOLDOWN_MINUTES,
}

# Test default prices (cents) used to build deterministic fixtures.
TEST_DEFAULTS = {
    "MILK_UNIT_CENTS": 349,
    "BANANA_WEIGHT_CENTS_PER_KG": 199,
    "GENERIC_UNIT_CENTS": 349,
}
