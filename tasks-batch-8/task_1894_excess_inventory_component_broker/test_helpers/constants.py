"""Domain thresholds and defaults — numeric constants from PRD business rules."""

THRESHOLDS = {
    # Urgency premiums over listing asking price (PRD section 3.6).
    "URGENCY_PREMIUM": {"STANDARD": 0.00, "PRIORITY": 0.10, "CRITICAL": 0.25},
    # Age discount buckets for final settlement pricing (PRD section 3.7).
    "AGE_FRESH_MAX_DAYS": 89,
    "AGE_AGED_MIN_DAYS": 90,
    "AGE_AGED_MAX_DAYS": 179,
    "AGE_STALE_MIN_DAYS": 180,
    "AGE_DISCOUNT_AGED": 0.05,
    "AGE_DISCOUNT_STALE": 0.12,
    # Market volatility dampener (PRD section 3.7).
    "VOLATILITY_DAMPENER_THRESHOLD": 0.20,
    "VOLATILITY_DAMPENER_RATE": 0.03,
    "VOLATILITY_WINDOW_SECONDS": 2_592_000,
    # Carrying value (PRD section 3.3).
    "DEPRECIATION_HORIZON_DAYS": 365,
    "BROKER_MARKET_HAIRCUT": 0.85,
    # Recommended listing price margin (PRD section 3.5).
    "RECOMMENDED_MARGIN": 1.10,
    # Asking-price cost floor ratio (PRD section 3.5).
    "COST_FLOOR_RATIO": 0.80,
    # Broker fee bounds in basis points (PRD section 3.4).
    "BROKER_FEE_BPS_MIN": 1,
    "BROKER_FEE_BPS_MAX": 5000,
    # Default payout terms on seller creation (PRD section 3.1).
    "DEFAULT_PAYOUT_TERMS_DAYS": 30,
}

TEST_DEFAULTS = {
    # Logical clock startup default (PRD section 2.4).
    "CLOCK_START": "2026-08-01T00:00:00Z",
    "ASK_PRICE": 5000,
    "AGREED_PRICE": 4000,
    "CREDIT_LIMIT": 1_000_000,
}
