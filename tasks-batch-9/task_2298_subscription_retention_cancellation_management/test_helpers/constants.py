"""Numeric constants and thresholds stated as literals in the PRD."""

# --- Global constants (PRD §2.4, §2.11, §3.5, §3.6, §3.7, §3.8) ---
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
MIN_REMINDER_LEAD_DAYS = 3
NOTICE_COOLDOWN_DAYS = 3
SESSION_TTL_HOURS = 48
MAX_CANCELLATION_STEPS = 4
MAX_PRE_COMPLETION_STEPS = 3
INVOLUNTARY_SUPPRESSION_DAYS = 30
VOLUNTARY_SAVE_SUPPRESSION_DAYS = 90
CONTACT_CAP_WINDOW_DAYS = 30
CONTACT_CAP = 1
POST_OFFER_HORIZON_CYCLES = 3
PRICE_CHANGE_NOTICE_LEAD_DAYS = 1

# --- Collections (PRD §3.7) ---
BASE_GRACE_DAYS_BY_TENURE = {
    "M0_1": 3,
    "M2_3": 5,
    "M4_6": 7,
    "M7_12": 10,
    "M13_PLUS": 14,
}
CARD_UPDATER_EXTENSION_DAYS = 4
BACKOFF_DAYS_BY_DECLINE = {
    "INSUFFICIENT_FUNDS": [1, 3, 5, 7],
    "EXPIRED_CARD": [0, 2, 4, 6],
    "DO_NOT_HONOR": [2, 4, 6, 8],
    "LOST_STOLEN": [0, 0, 0, 0],
}
MAX_RETRY_ATTEMPTS = 4

# --- Lifetime value (PRD §3.9) ---
CHANNEL_BASE_CHURN = {
    "PAID_SOCIAL": 0.10,
    "SEARCH": 0.07,
    "AFFILIATE": 0.12,
    "ORGANIC": 0.05,
    "REFERRAL": 0.04,
}
TENURE_MULTIPLIER = {
    "M0_1": 1.6,
    "M2_3": 1.2,
    "M4_6": 1.0,
    "M7_12": 0.8,
    "M13_PLUS": 0.6,
}
HORIZON_CYCLES_CAP = 24
LTV_NORMALIZER_CENTS = 20000

# --- Win-back scoring (PRD §3.8) ---
REASON_WEIGHT = {
    "PRICE": 1.0,
    "TOO_MUCH_PRODUCT": 0.8,
    "FINANCIAL_HARDSHIP": 0.7,
    "SHIPPING_ISSUES": 0.6,
    "PRODUCT_FIT": 0.4,
    "OTHER": 0.2,
}
INVOLUNTARY_SCORE_CEILING = 0.4000
RECENT_SAVE_OFFER_DAYS = 90
GRANT_WINDOW_DAYS = 365

# --- Tenure bucketing (PRD §3.9) ---
TENURE_BUCKET_MONTH_DIVISOR = 30

# --- Pagination (PRD §2.3) ---
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Canonical catalogue values reused by fixtures ---
CORE_PLAN = {
    "code": "CORE",
    "name": "Core Box",
    "monthly_price_cents": 4999,
    "unit_cogs_cents": 2100,
    "margin_floor_pct": 0.4200,
    "addon_catalog": [
        {"code": "MUG", "unit_price_cents": 1299, "unit_cogs_cents": 520},
        {"code": "TUMBLER", "unit_price_cents": 899, "unit_cogs_cents": 360},
    ],
}
LITE_PLAN = {
    "code": "LITE",
    "name": "Lite Box",
    "monthly_price_cents": 2999,
    "unit_cogs_cents": 1400,
    "margin_floor_pct": 0.4000,
}
CANONICAL_CARD = {
    "card_last4": "4242",
    "exp_month": 12,
    "exp_year": 2030,
    "network": "VISA",
}
