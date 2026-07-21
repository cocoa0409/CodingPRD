"""Domain thresholds — numeric constants drawn from the PRD's pricing, loyalty,
rental-settlement, and temporal rules. Generic NON_EXISTENT_UUID comes from the
framework.
"""

# ---- Loyalty discount tiers (settled tier -> base discount rate) ----
TIER_RATE = {"BRONZE": 0.00, "SILVER": 0.05, "GOLD": 0.10}
SUBSCRIBER_PERK_RATE = 0.05
MAX_DISCOUNT_RATE = 0.20

# ---- Loyalty tier thresholds over lifetime_points (inclusive) ----
SILVER_THRESHOLD = 2000
GOLD_THRESHOLD = 5000

# ---- Shipping ----
FREE_SHIP_THRESHOLD_CENTS = 8000
FLAT_SHIP_CENTS = 799

# ---- Rental settlement ----
LATE_FEE_PER_DAY_CENTS = 500
DAYS_PER_WEEK = 7
LOST_GRACE_DAYS = 14
CLEANING_BUFFER_DAYS = 2

# ---- Capsule ----
CAPSULE_KEEP_PCT = 0.70
CAPSULE_LOAN_DAYS = 30

# ---- Returns ----
RESTOCK_RATE = 0.10
RETURN_WINDOW_DAYS = 30

# ---- Fit guide ----
SIZE_ORDER = ["XS", "S", "M", "L", "XL"]

# ---- Trimester ----
FULL_TERM_WEEKS = 40

# ---- Pagination ----
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# ---- Logical clock startup default ----
CLOCK_STARTUP_DEFAULT = "2026-07-01T00:00:00Z"
