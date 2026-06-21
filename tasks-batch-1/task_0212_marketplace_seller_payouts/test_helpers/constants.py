"""Domain thresholds — numeric constants from the PRD calculations (Section 3)."""

# Risk score factor weights (PRD §3.10).
RISK_WEIGHTS = {
    "W_CB": 0.6,
    "W_REF": 0.25,
    "W_DISP": 0.15,
}

# risk_tier thresholds (PRD §3.10): score < 20 STANDARD; 20 <= score < 50 ELEVATED; >= 50 HIGH.
RISK_TIER_THRESHOLDS = {
    "ELEVATED_MIN": 20,
    "HIGH_MIN": 50,
}

# Flat non-refundable chargeback fee (PRD §3.7).
CHARGEBACK_FEE_CENTS = 1500

# 1099-K thresholds (PRD §3.11), inclusive (>=).
FEDERAL_THRESHOLD_CENTS = 500000      # $5,000
LEGACY_THRESHOLD_CENTS = 2000000      # $20,000
LEGACY_TXN_THRESHOLD = 200

# Pagination bounds (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# The canonical ELECTRONICS fee schedule used throughout the design indices:
# commission_bps 1500, fixed_fee_cents 50, payment_processing_bps 290,
# payment_processing_fixed_cents 30, reserve tiers 0/20/50, maturation_days 7.
ELECTRONICS_SCHEDULE = {
    "category": "ELECTRONICS",
    "commission_bps": 1500,
    "fixed_fee_cents": 50,
    "payment_processing_bps": 290,
    "payment_processing_fixed_cents": 30,
    "reserve_pct_standard": 0,
    "reserve_pct_elevated": 20,
    "reserve_pct_high": 50,
    "maturation_days": 7,
}

MEDIA_SCHEDULE = {
    "category": "MEDIA",
    "commission_bps": 1200,
    "fixed_fee_cents": 40,
    "payment_processing_bps": 290,
    "payment_processing_fixed_cents": 30,
    "reserve_pct_standard": 0,
    "reserve_pct_elevated": 20,
    "reserve_pct_high": 50,
    "maturation_days": 7,
}
