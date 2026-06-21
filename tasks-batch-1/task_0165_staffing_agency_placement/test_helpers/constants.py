"""Domain thresholds and numeric constants from the PRD calculation rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Overtime (PRD 3.6: regular portion <= 40h; overtime strictly above 40h at 1.5x)
OT_THRESHOLD_HOURS = 40
OT_MULTIPLIER = 1.5
OT_BILL_MULTIPLIER = 1.5

# Invoice total tiers (PRD 3.8)
TIER_NONE_RATE = 0.0          # subtotal < 500000  -> no discount
TIER_1_MIN_CENTS = 500000     # 500000 <= subtotal < 2000000 -> 3%
TIER_1_RATE = 0.03
TIER_2_MIN_CENTS = 2000000    # subtotal >= 2000000 -> 6%
TIER_2_RATE = 0.06
PROCESSING_FEE_PCT = 0.015    # 1.5% on the post-discount amount

# Conversion fee (PRD 3.7)
TENURE_DISCOUNT_WEEKS = 13
TENURE_DISCOUNT_FACTOR = 0.5
MIN_FEE_CENTS = 250000
MAX_FEE_CENTS = 5000000
DEFAULT_CONVERSION_FEE_PCT = 0.20

# Pagination (PRD 2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Common test values reused across fixtures.
TEST_DEFAULTS = {
    "BILL_RATE_CENTS": 12000,
    "PAY_RATE_CENTS": 8000,
    "STANDARD_WEEKLY_HOURS": 40,
    "BIG_CREDIT_LIMIT": 100000000,
}
