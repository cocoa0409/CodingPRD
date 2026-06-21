"""Domain thresholds — numeric constants from the Meal Kit Subscription PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Per-serving tier rates (PRD §3.6, step 2): chosen by total servings.
PER_SERVING_RATE = {
    "TIER_16_PLUS": 899,    # total_servings >= 16
    "TIER_8_TO_15": 999,    # 8 <= total_servings < 16
    "TIER_UNDER_8": 1099,   # total_servings < 8
}
SERVING_TIER_GOLD_MIN = 16   # >= 16 servings -> 899
SERVING_TIER_SILVER_MIN = 8  # >= 8 servings -> 999

# Diet premium per serving (PRD §3.6, step 3).
DIET_PREMIUM = {
    "STANDARD": 0,
    "VEGETARIAN": 0,
    "PESCATARIAN": 150,
    "LOW_CARB": 200,
    "FAMILY_FRIENDLY": 0,
}

# Premium recipe upcharge per premium slot (PRD §3.6, step 4).
PREMIUM_RECIPE_UPCHARGE = 400

# Loyalty discount tiers on lifetime_box_count (PRD §3.6, step 7).
LOYALTY_GOLD_MIN = 24    # >= 24 -> 10%
LOYALTY_SILVER_MIN = 12  # 12..23 -> 5%
LOYALTY_GOLD_PCT = 0.10
LOYALTY_SILVER_PCT = 0.05

# Referral credit cap applied per box (PRD §3.6, step 10).
REFERRAL_CREDIT_CAP_PER_BOX = 2000

# Pause proration cycle length in days (PRD §3.6 pause proration).
PRORATION_CYCLE_DAYS = 30

# Referral program constants (PRD §3.7).
REFERRAL_REWARD_CENTS = 1500
MAX_REFERRAL_REWARDS_PER_CYCLE = 3

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Convenience aggregate dict for tests that prefer keyed lookup.
THRESHOLDS = {
    "SERVING_TIER_GOLD_MIN": SERVING_TIER_GOLD_MIN,
    "SERVING_TIER_SILVER_MIN": SERVING_TIER_SILVER_MIN,
    "PREMIUM_RECIPE_UPCHARGE": PREMIUM_RECIPE_UPCHARGE,
    "REFERRAL_CREDIT_CAP_PER_BOX": REFERRAL_CREDIT_CAP_PER_BOX,
    "PRORATION_CYCLE_DAYS": PRORATION_CYCLE_DAYS,
    "REFERRAL_REWARD_CENTS": REFERRAL_REWARD_CENTS,
    "MAX_REFERRAL_REWARDS_PER_CYCLE": MAX_REFERRAL_REWARDS_PER_CYCLE,
}
