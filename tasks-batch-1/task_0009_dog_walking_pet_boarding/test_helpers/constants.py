"""Domain thresholds: numeric constants from the PRD's calculation tables."""

# booking_quote table — base rate by service type (cents).
BASE_RATE_BY_SERVICE = {
    "WALK_30MIN": 2000,
    "WALK_60MIN": 3500,
    "BOARDING_OVERNIGHT": 8000,
    "DAYCARE": 5000,
}

# booking_quote tier multipliers.
TIER_MULT = {
    "BRONZE": 1.00,
    "SILVER": 1.15,
    "GOLD": 1.30,
}

# booking_quote time-of-day factor.
TIME_FACTOR = {
    "STANDARD": 1.00,
    "PEAK": 1.20,
    "OVERNIGHT": 1.30,
}

# booking_quote recurring discount.
RECUR_DISCOUNT = {
    "NONE": 0.00,
    "WEEKLY": 0.10,
    "BIWEEKLY": 0.05,
}

# sitter_tier_score weights and thresholds.
TIER_SCORE = {
    "W_RATING": 0.5,
    "W_BOOKINGS": 0.3,
    "BASE": 10,
    "CLAIM_PENALTY": 15,
    "CLAIM_CAP": 45,
    "BOOKINGS_CAP": 40,
    "SILVER_MIN": 40,
    "GOLD_MIN": 70,
    "NEUTRAL_RATING_SCORE": 60,  # used when total_rating_count == 0.
}

# sitter_payout platform fee.
PLATFORM_FEE_PCT = 0.15

# claim_payout deductible table (cents) keyed by sitter_tier_snapshot.
TIER_DEDUCTIBLE = {
    "BRONZE": 10000,
    "SILVER": 5000,
    "GOLD": 2500,
}

# claim_payout platform-wide maximum payout.
MAX_PAYOUT_CENTS = 500000

# No-show window for Meet & Greet (minutes).
MEET_AND_GREET_NO_SHOW_MINUTES = 60

# Sitter calendar trailing travel buffer (minutes).
SITTER_TRAILING_BUFFER_MINUTES = 30

# Wallet starting balance for newly-registered Owner.
INITIAL_WALLET_CREDIT_CENTS = 0
