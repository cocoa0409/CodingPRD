"""Domain thresholds — numeric constants from PRD §3 pricing/loyalty narratives."""

# Loyalty discount fractions by tier (PRD §3.2).
LOYALTY_PCT = {
    "STANDARD": 0.00,
    "SILVER": 0.05,
    "GOLD": 0.10,
}

# Combined loyalty+recurring discount cap (PRD §3.2).
COMBINED_DISCOUNT_CAP = 0.30

# Loyalty promotion thresholds on lifetime_delivered_count (PRD §3.5).
SILVER_THRESHOLD = 5
GOLD_THRESHOLD = 15

# Claim refund reason fractions and per-reason floor cents (PRD §3.7).
REASON_PCT = {
    "WILTED": 0.50,
    "WRONG_ITEM": 1.00,
    "LATE": 0.25,
    "DAMAGED": 0.75,
}
REASON_FLOOR_CENTS = {
    "WILTED": 500,
    "WRONG_ITEM": 0,
    "LATE": 300,
    "DAMAGED": 1000,
}

# Final total floor (PRD §3.5 — final_total_cents never negative).
MIN_TOTAL_CENTS = 0

# Default arrangement substitution cap fraction (PRD §3.1).
DEFAULT_SUBSTITUTION_CAP_PCT = 0.15

TEST_DEFAULTS = {
    "BASE_PRICE_CENTS": 5000,
    "DELIVERY_FEE_CENTS": 800,
    "SAME_DAY_CUTOFF_HOUR": 14,
    "WINDOW_CAPACITY": 5,
    "DAILY_CAPACITY": 5,
    "WINDOW_START_MINUTE": 540,
    "WINDOW_END_MINUTE": 720,
}
