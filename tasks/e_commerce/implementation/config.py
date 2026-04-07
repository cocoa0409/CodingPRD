"""Application constants derived from PRD business rules."""

RESERVATION_TIMEOUT_MINUTES = 30

COMMISSION_TIERS = [
    {"lower": 0,     "upper": 10_000, "rate": 0.08},
    {"lower": 10_000, "upper": 50_000, "rate": 0.05},
    {"lower": 50_000, "upper": float("inf"), "rate": 0.03},
]

PAGINATION_DEFAULT_LIMIT = 20
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_LIMIT = 1

MIN_ORDER_TOTAL = 0.01

VALID_ROLES = {"Customer", "Seller", "PlatformAdmin"}
VALID_PAYMENT_METHODS = {"CREDIT_CARD", "DEBIT_CARD", "WALLET", "BANK_TRANSFER"}
VALID_PROMO_TYPES = {"PERCENTAGE", "FIXED_AMOUNT", "BUY_X_GET_Y_FREE"}
VALID_DISCOUNT_STRATEGIES = {"PERCENTAGE_FIRST", "FIXED_FIRST"}
