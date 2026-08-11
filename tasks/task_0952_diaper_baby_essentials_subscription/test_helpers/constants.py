"""Domain thresholds and constants stated in the PRD narrative."""

# The logical clock's value before any operator sets it (PRD section 2.5).
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# The instant every fixture pins the clock to unless a test says otherwise.
BASE_CLOCK_UTC = "2026-06-01T00:00:00Z"

# --- size / stage ladder (PRD section 3.2) --------------------------------
STAGE_ORDER = [
    "NEWBORN",
    "S1",
    "S2",
    "S3",
    "S4",
    "S5",
    "S6",
    "PULL_UP_2T3T",
    "PULL_UP_3T4T",
    "PULL_UP_4T5T",
]

# Each band is [min inclusive, max exclusive) in grams.
STAGE_BANDS = {
    "NEWBORN": (0, 4500),
    "S1": (4500, 6400),
    "S2": (6400, 8200),
    "S3": (8200, 11000),
    "S4": (11000, 14000),
    "S5": (14000, 17000),
    "S6": (17000, 20000),
    "PULL_UP_2T3T": (20000, 23000),
    "PULL_UP_3T4T": (23000, 26000),
    "PULL_UP_4T5T": (26000, 60000),
}

THRESHOLDS = {
    # weight
    "WEIGHT_MIN_G": 500,
    "WEIGHT_MAX_G": 59999,
    # auto resize
    "AUTO_RESIZE_CAP_PER_PERIOD": 2,
    "AUTO_RESIZE_PERIOD_DAYS": 90,
    "MAX_STAGE_STEP_PER_RESIZE": 1,
    # cadence
    "CYCLE_LEAD_DAYS": 7,
    "CYCLE_CUTOFF_HOURS_BEFORE_SHIP": 48,
    "CADENCE_MIN_INTERVAL_DAYS": 14,
    "CADENCE_MAX_INTERVAL_DAYS": 56,
    "UNITS_PER_PACK_DEFAULT": 60,
    "PACK_COUNT_MIN": 1,
    "PACK_COUNT_MAX": 12,
    "CONSUMPTION_RATE_MIN_PER_DAY": 1,
    "CONSUMPTION_RATE_MAX_PER_DAY": 14,
    # skip / pause
    "SKIP_ALLOWANCE_PER_WINDOW": 2,
    "SKIP_WINDOW_DAYS": 180,
    "PAUSE_MAX_CUMULATIVE_DAYS": 90,
    # allergen / substitution
    "SUBSTITUTION_ATTEMPT_CAP": 3,
    "HYPOALLERGENIC_SURCHARGE_CENTS": 350,
    # credits
    "CREDIT_EXPIRY_DAYS": 365,
    "GIFT_CREDIT_EXPIRY_DAYS": 730,
    "REFERRAL_CREDIT_MAX_PCT": 0.50,
    "LOYALTY_REDEMPTION_MAX_PCT": 0.30,
    "PROMO_DISCOUNT_MAX_PCT": 0.25,
    # loyalty
    "POINT_REDEMPTION_FLOOR_POINTS": 500,
    "POINT_VALUE_CENTS": 1,
    "POINTS_EARN_DIVISOR_CENTS": 100,
    "POINTS_EXPIRY_DAYS": 540,
    "TIER_EVAL_WINDOW_DAYS": 365,
    "TIER_SILVER_THRESHOLD_POINTS": 2000,
    "TIER_GOLD_THRESHOLD_POINTS": 6000,
    "TIER_MULTIPLIER_BRONZE": 1.00,
    "TIER_MULTIPLIER_SILVER": 1.25,
    "TIER_MULTIPLIER_GOLD": 1.50,
    # referral
    "REFERRAL_CREDIT_CENTS": 1500,
    "REFERRAL_PROMO_CREDIT_CENTS": 3000,
    "REFERRAL_CAP_PER_PERIOD": 5,
    "REFERRAL_PERIOD_DAYS": 365,
    "REFERRAL_VEST_WINDOW_DAYS": 120,
    # registry / gift
    "REGISTRY_REOPEN_CAP": 1,
    "GIFT_CLAIM_WINDOW_DAYS": 60,
    "REGISTRY_ITEM_QTY_MAX": 20,
    # shipping
    "SHIPPING_BASE_CENTS": 599,
    "SHIPPING_HEAVY_SURCHARGE_CENTS": 250,
    "SHIPPING_HEAVY_THRESHOLD_UNITS": 240,
    "FREE_SHIPPING_SUBTOTAL_CENTS": 4900,
    "SHIPMENT_SPACING_BUFFER_HOURS": 12,
    "SHIPMENT_EXCEPTION_RETRY_CAP": 2,
    "SHIPMENT_ETA_DAYS_STANDARD": 3,
    "SHIPMENT_ETA_DAYS_EXPEDITED": 1,
    # cancellation / billing
    "RESTOCK_FEE_CENTS": 600,
    "DELINQUENCY_GRACE_DAYS": 14,
}

# The referral promotional window is half-open [start, end).
REFERRAL_PROMO_WINDOW_START_UTC = "2026-11-01T00:00:00Z"
REFERRAL_PROMO_WINDOW_END_UTC = "2026-12-01T00:00:00Z"

TEST_DEFAULTS = {
    "PLAN_CODE": "CORE",
    "PLAN_NAME": "Core Plan",
    "PLAN_DEFAULT_PACK_COUNT": 2,
    "SKU_PRICE_CENTS": 1200,
    "SKU_PACK_SIZE_UNITS": 60,
    "SKU_STOCK_PACKS": 50,
    "CONSUMPTION_RATE_PER_DAY": 6,
    "PACK_COUNT": 2,
    "CHILD_WEIGHT_GRAMS": 7000,  # resolves to stage S2
    "CHILD_BIRTH_DATE": "2025-11-01",
}
