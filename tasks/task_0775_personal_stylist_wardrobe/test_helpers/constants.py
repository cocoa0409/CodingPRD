"""Domain thresholds — numeric constants from the PRD's pricing calculations."""

# --- Session charge (billing blocks) ---
BILLING_BLOCK_MINUTES = 15
MIN_BILLABLE_BLOCKS = 4

# --- Retail markup tiers ---
TIER_LOW_MAX = 5000        # retail < 5000  -> MARKUP_LOW
TIER_MID_MAX = 20000       # 5000 <= retail < 20000 -> MARKUP_MID; >= 20000 -> MARKUP_HIGH
MARKUP_LOW = 0.30
MARKUP_MID = 0.20
MARKUP_HIGH = 0.10

# --- Invoice totals ---
STYLING_FEE_PCT = 0.10
VOLUME_TIER_1_MIN = 50000
VOLUME_TIER_1_PCT = 0.05
VOLUME_TIER_2_MIN = 100000
VOLUME_TIER_2_PCT = 0.10

# --- Referral credit ---
REFERRAL_ESTIMATE_CENTS = 5000
REFERRAL_RATE_PCT = 0.10
REFERRAL_CAP_CENTS = 10000

# --- Time windows ---
CLIENT_BUFFER_MINUTES = 60
SUBSCRIPTION_PERIOD_DAYS = 90
REFERRAL_EXPIRY_DAYS = 90

# --- Subscription refresh credits by tier ---
SILVER_REFRESH_CREDITS = 2
GOLD_REFRESH_CREDITS = 4

# --- Logical clock ---
CLOCK_STARTUP_UTC = "2026-03-01T00:00:00Z"

# Convenience default used across many fixtures.
DEFAULT_BLOCK_RATE_CENTS = 3000
