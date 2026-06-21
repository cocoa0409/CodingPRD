"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Missed-pickup credit (PRD §3.8)
STREAM_CREDIT_CENTS = {"TRASH": 300, "RECYCLING": 200}
REPEAT_THRESHOLD = 2          # "strictly greater than 2" prior misses escalates
REPEAT_BONUS_CENTS = 150
MISSED_CREDIT_WINDOW_DAYS = 90

# Contamination fee (PRD §3.9)
MINOR_FEE_CENTS = 1500
MAJOR_MULTIPLIER = 2
MAJOR_FEE_CENTS = MINOR_FEE_CENTS * MAJOR_MULTIPLIER  # 3000

# Extra-pickup charge (PRD §3.10)
FREE_BULK_ALLOWANCE = 2       # first two bulk items included in base

# Invoice gross (PRD §3.11)
PROVISIONED_CART_COUNT = 2    # one TRASH + one RECYCLING provisioned per plan

# Billing dimension (PRD §3.13)
COLLECTIONS_THRESHOLD_DAYS = 60

# Schedule generation horizon (PRD §3.3)
SCHEDULE_HORIZON_DAYS = 28

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_LIMIT = 1

# Reusable STANDARD plan rate card used across the design indices.
STANDARD_PLAN = {
    "tier": "STANDARD",
    "trash_cart_size_gallons": 65,
    "recycling_cart_size_gallons": 65,
    "monthly_base_cents": 4000,
    "extra_cart_monthly_cents": 1200,
    "extra_pickup_base_cents": 2500,
    "bulk_item_cents": 800,
}

BASIC_PLAN = {
    "tier": "BASIC",
    "trash_cart_size_gallons": 35,
    "recycling_cart_size_gallons": 35,
    "monthly_base_cents": 3000,
    "extra_cart_monthly_cents": 1000,
    "extra_pickup_base_cents": 2000,
    "bulk_item_cents": 600,
}
