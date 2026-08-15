"""Domain constants — numeric thresholds and recipes from the PRD."""

# Logical clock (PRD §2.4): on startup the clock reads 2026-08-01T00:00:00Z.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
TEST_CLOCK_ISO = "2026-08-01T08:00:00Z"
TEST_EFFECTIVE_DATE = "2026-08-01"

# Contract window covering the whole test year (PRD §3.2).
CONTRACT_START_DATE = "2026-01-01"
CONTRACT_END_DATE = "2026-12-31"

# Tax rule effective window covering the whole test year (PRD §3.1).
TAX_WINDOW_START = "2026-01-01"
TAX_WINDOW_END = "2026-12-31"

# Contract pricing-tier per-gallon discounts in cents (PRD §3.3).
TIER_DISCOUNT_CENTS = {
    "RACK": 0,
    "RACK_MINUS_1": 1,
    "RACK_MINUS_2": 2,
}

# California branded-blend uplift in cents per gallon at the STATE level
# (PRD §3.6).
CA_BRANDED_UPLIFT_CENTS_PER_GAL = 2

# Additive injection recipes (PRD §3.6): each line is
# (rate_millicents_per_gal, flat_fee_cents); every line is converted to cents
# and rounded half up before the lines are summed (PRD §2.6).
ADDITIVE_RECIPES = {
    "PKG_A": [(250, 500), (100, 0)],
    "PKG_B": [(175, 750)],
    "PKG_C": [(333, 0), (167, 250), (100, 0)],
}

# BOL reversal window in logical hours (PRD §3.7).
REVERSAL_WINDOW_HOURS = 24

TEST_DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 1_000_000_000,
    "DAILY_RATABLE_GALLONS": 100_000,
    "VOLUME_COMMITMENT_GALLONS": 100_000,
    "MONTHLY_EXCHANGE_CAP_GALLONS": 100_000,
    "POSTED_RACK_CENTS_PER_GAL": 280,
}
