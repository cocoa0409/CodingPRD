"""Domain thresholds and multipliers — numeric constants from the PRD calculations."""

# Order-charge pricing (PRD 3.3 / 3.6)
TERM_MULT = {30: 0.5, 60: 0.75, 90: 1.0, 120: 1.25}
LOYALTY_THRESHOLD_CENTS = 10000
LOYALTY_CREDIT_CENTS = 500

# Buyback pricing (PRD 3.7)
COND_MULT = {"NEW": 1.0, "LIKE_NEW": 0.9, "GOOD": 0.75, "ACCEPTABLE": 0.5}

# Late fee (PRD 3.6)
GRACE_DAYS = 3
DAILY_LATE_FEE_CENTS = 250
LOST_THRESHOLD_DAYS = 30

# Damage fee (PRD 3.6)
GRADE_RANK = {"NEW": 0, "LIKE_NEW": 1, "GOOD": 2, "ACCEPTABLE": 3}
CONDITION_STEP_FEE_CENTS = 1500
HIGHLIGHT_FEE_PER_PCT_CENTS = 200
HIGHLIGHT_BANNED_FLAT_CENTS = 2500

# Subscription (PRD 3.2)
DAYS_PER_MONTH = 30

# Extensions (PRD 3.5)
EXTENSION_FEE_CENTS = 1500
EXTENSION_TERM_DAYS = 30
MAX_EXTENSIONS = 2
MAX_TOTAL_TERM_DAYS = 210

# Fulfilment selector (PRD 3.4)
INSPECTION_BUFFER_DAYS = 2

# Quote validity (PRD 3.7): quote_expires_at = created_at + 7 days
QUOTE_VALIDITY_DAYS = 7

# Default catalog price points used across setup (all in cents).
CATALOG_DEFAULTS = {
    "list_price_cents": 12000,
    "rental_base_cents": 6000,
    "ebook_price_cents": 4000,
    "buyback_base_cents": 3000,
    "replacement_fee_cents": 10000,
}
