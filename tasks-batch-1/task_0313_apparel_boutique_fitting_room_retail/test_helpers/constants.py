"""Domain thresholds — numeric constants from PRD pricing and loyalty rules."""

# Loyalty tier thresholds (cumulative net captured spend, in cents)
LOYALTY_THRESHOLDS = {
    "SILVER_THRESHOLD_CENTS": 50_000,
    "GOLD_THRESHOLD_CENTS": 150_000,
}

# Tier discount rates in basis points, applied at order authorization
TIER_DISCOUNT_BPS = {
    "STANDARD": 0,
    "SILVER": 500,
    "GOLD": 1000,
}

# One loyalty point per this many cents of net cash paid
POINTS_DIVISOR_CENTS = 100

# Minimum price floor in cents (no computed price may fall below one dollar)
MIN_PRICE_CENTS = 100

# Default mandatory cleanup gap between stylist appointments
DEFAULT_STYLIST_BUFFER_MINUTES = 15

# Default days a completed order remains returnable
DEFAULT_RETURN_WINDOW_DAYS = 30

TEST_DEFAULTS = {
    "TAX_RATE_BPS": 875,
    "TAX_RATE_BPS_ZERO": 0,
}
