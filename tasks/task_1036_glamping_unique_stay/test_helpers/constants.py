"""Domain thresholds — numeric constants from the PRD pricing and refund rules."""

# Fee and discount rates (PRD §3.5, §3.6).
RATES = {
    "GUEST_FEE_RATE": 0.12,       # guest service fee on the stay subtotal
    "HOST_FEE_RATE": 0.03,        # host fee on stay-and-add-ons revenue
    "WEEKLY_DISCOUNT_PCT": 0.10,  # applies at >= 7 nights
    "MONTHLY_DISCOUNT_PCT": 0.28,  # applies at >= 28 nights
}

# Length-of-stay discount night thresholds (PRD §3.5).
DISCOUNT_NIGHT_THRESHOLDS = {
    "WEEKLY_MIN_NIGHTS": 7,
    "MONTHLY_MIN_NIGHTS": 28,
}

# Cancellation refund tier day thresholds (PRD §3.8).
REFUND_DAY_THRESHOLDS = {
    "FLEXIBLE_FULL_MIN_DAYS": 1,
    "MODERATE_FULL_MIN_DAYS": 7,
    "MODERATE_HALF_MIN_DAYS": 1,
    "STRICT_HALF_MIN_DAYS": 14,
}

# Logical clock (PRD §2.5): startup default instant.
DEFAULT_CLOCK_UTC = "2026-07-01T00:00:00Z"

# Pagination defaults (PRD §2.3).
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}
