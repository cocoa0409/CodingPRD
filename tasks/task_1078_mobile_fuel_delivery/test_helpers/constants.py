"""Domain thresholds — numeric constants from the Mobile Fuel Delivery PRD calculations."""

THRESHOLDS = {
    # service_fee tiers (PRD §3.7)
    "BASE_DELIVERY_FEE_CENTS": 1200,
    "MEMBER_OVERAGE_FEE_CENTS": 600,
    "PRIORITY_SURCHARGE_CENTS": 500,
    # membership settlement (PRD §3.8)
    "UNUSED_DELIVERY_CREDIT_CENTS": 400,
    "MEMBERSHIP_PERIOD_DAYS": 30,
    # add-on catalog + discount (PRD §3.7)
    "CAR_WASH_PRICE_CENTS": 1595,
    "OIL_CHANGE_PRICE_CENTS": 6495,
    "MEMBER_ADDON_DISCOUNT_PCT": 0.10,
    # per-gallon member fuel discount (PRD §3.7)
    "MEMBER_DISCOUNT_PER_GALLON_CENTS": 10,
    # temporal buffer (PRD §3.4)
    "SERVICE_BUFFER_MINUTES": 60,
    # pagination (PRD §2.3)
    "PAGINATION_DEFAULT_LIMIT": 10,
    "PAGINATION_MAX_LIMIT": 100,
}

TEST_DEFAULTS = {
    "DEFAULT_CLOCK": "2026-05-01T00:00:00Z",
    "REGULAR_PRICE_CENTS": 419,
    "DIESEL_PRICE_CENTS": 459,
    "PREMIUM_PRICE_CENTS": 489,
}
