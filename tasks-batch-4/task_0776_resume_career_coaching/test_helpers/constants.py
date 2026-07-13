"""Domain thresholds — numeric constants from the PRD's pricing and scoring rules."""

# Fixed add-on price list (PRD §3.2 / §3.6), in integer cents.
ADDON_PRICES = {
    "EXTRA_REVISION": 4000,
    "EXTRA_COACHING": 12000,
    "EXTRA_DELIVERABLE": 9000,
    "INTERVIEW_PREP": 15000,
    "RUSH": 0,
}

# Session overage fees by session_type (PRD §3.5), in integer cents.
SESSION_PRICES = {
    "COACHING": 12000,
    "INTERVIEW_PREP": 15000,
}

# Pricing constants (PRD §3.2).
ADDON_VOLUME_DISCOUNT_PCT = 0.10          # applies only when addon_count >= 3
ADDON_VOLUME_DISCOUNT_MIN_COUNT = 3
COUPON_WELCOME10_PCT = 0.10               # of base_price_cents
COUPON_SAVE50_FLAT = 5000                 # min(5000, subtotal_before_discount)
EXTRA_REVISION_PRICE_CENTS = 4000

# Defaults (PRD §3.1).
DEFAULT_BUFFER_MINUTES = 15
DEFAULT_RUSH_SURCHARGE_PCT = 0.30

# Logical clock default at server startup (PRD §2.11).
CLOCK_DEFAULT_UTC = "2026-03-01T00:00:00Z"

# Guarantee eligibility windows (PRD §3.7), in days.
SATISFACTION_WINDOW_DAYS = 14
INTERVIEW_WINDOW_DAYS = 90
