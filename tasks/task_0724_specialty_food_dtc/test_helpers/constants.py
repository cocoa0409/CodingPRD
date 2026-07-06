"""Domain thresholds — numeric constants from PRD calculations (§3.6, §3.7, §3.9, §3.10, §3.11)."""

# --- Order pricing (PRD §3.6) ---
PERISHABLE_HANDLING_CENTS = 450
PERISHABLE_SHIP_MULT = 1.5
LOYALTY_MAX_REDEEM_PCT = 0.30
ZONE_BASE = {"Z1": 500, "Z2": 800, "Z3": 1200, "Z4": 1800}
# Volume tiers keyed on pre-discount subtotal.
# subtotal >= 20000 -> 0.15; >= 10000 -> 0.10; >= 5000 -> 0.05; else 0.0

# --- Loyalty accrual (PRD §3.7) ---
EARN_RATE_PER_CENT = 0.015

# --- Subscription renewal charge (PRD §3.9) ---
TIER_MONTHLY = {"STARTER": 2900, "CLASSIC": 4900, "RESERVE": 8900}
LOYALTY_TIER_DISCOUNT = {"STARTER": 0.0, "CLASSIC": 0.05, "RESERVE": 0.10}

# --- Churn risk score (PRD §3.10) ---
W_RECENCY = 40
W_SKIP = 35
W_FAIL = 25
RECENCY_DIVISOR_DAYS = 60
SKIP_DIVISOR = 5
FAIL_DIVISOR = 3
CHURN_WINDOW_DAYS = 90

# --- Referral reward (PRD §3.1) ---
REFERRAL_REWARD_POINTS = 500

# --- Corporate bulk quote (PRD §3.11) ---
GIFT_WRAP_CENTS = 350
# BULK_TIER keyed on pre-discount line_subtotal:
# >=100000 -> (0.20, 0.03); >=50000 -> (0.12, 0.04); >=20000 -> (0.07, 0.05); else (0.0, 0.06)

# --- Subscription skip auto-pause limit (PRD §3.8) ---
SKIP_AUTOPAUSE_LIMIT = 3

# --- Logical clock default (PRD §2.5) ---
CLOCK_DEFAULT_ISO = "2026-03-01T00:00:00Z"

# A far-future expiry so lots are in-date under the default clock.
FAR_EXPIRY_ISO = "2026-12-01T00:00:00Z"

TEST_DEFAULTS = {
    "UNIT_PRICE_CENTS": 1000,
    "PRODUCED_UNITS": 50,
}
