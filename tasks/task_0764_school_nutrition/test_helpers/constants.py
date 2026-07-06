"""Domain thresholds — numeric constants from the PRD's calculations and defaults."""

# Meal-pattern compliance minimums (PRD §3.2)
MEAL_PATTERN = {
    "MIN_MEAT_LUNCH": 1.0,
    "MIN_GRAIN_LUNCH": 1.0,
    "MIN_FV_LUNCH": 0.75,
    "MIN_GRAIN_BREAKFAST": 1.0,
    "MIN_FV_BREAKFAST": 0.5,
}

# Production forecast (PRD §3.4)
PARTICIPATION_FACTOR = 0.9

# Offer-vs-serve minimum distinct components (PRD §3.6)
OVS_MIN_COMPONENTS_LUNCH = 3
OVS_MIN_COMPONENTS_BREAKFAST = 3

# A-la-carte sales-tax denominator (PRD §3.6)
TAX_DENOMINATOR = 10000

# Smart-Snacks screen limits (PRD §3.6)
SMART_SNACK_MAX_CALORIES = 200
SMART_SNACK_MAX_SODIUM_MG = 200

# Site default price/copay fields, in cents (PRD §3.1)
SITE_DEFAULTS = {
    "paid_lunch_price_cents": 300,
    "paid_breakfast_price_cents": 200,
    "reduced_lunch_copay_cents": 40,
    "reduced_breakfast_copay_cents": 30,
    "sales_tax_bps": 0,
}

# Student default low-balance threshold, in cents (PRD §3.5)
DEFAULT_LOW_BALANCE_THRESHOLD_CENTS = 500

# Server logical clock startup default (PRD §2.10)
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"
