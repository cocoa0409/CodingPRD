"""Domain thresholds — numeric constants from PRD calculations."""

# Return program constants (PRD §3.6): the restocking fee is 1000 basis points
# of the snapshotted unit price per unit, and the return window runs 7 days
# from distribution_completed_at.
THRESHOLDS = {
    "RESTOCK_FEE_BPS": 1000,
    "RETURN_WINDOW_DAYS": 7,
    # Fixed bounce fee posted as BOUNCE_FEE_DEBIT to the order's group when a
    # cleared check bounces (observed: 1500 cents).
    "BOUNCE_FEE_CENTS": 1500,
    "MAX_BPS": 10000,
}

# Logical clock startup default (PRD §2.5).
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "CAMPAIGN_NAME": "Fall Sale",
    "SCHOOL_NAME": "Lincoln",
    "ORDER_WINDOW_START": "2026-08-01T00:00:00Z",
    "ORDER_WINDOW_END": "2026-08-20T00:00:00Z",
    "EXPECTED_DELIVERY_DATE": "2026-09-05T00:00:00Z",
    "DEFAULT_PROFIT_SHARE_BPS": 5000,
    "UNIT_PRICE_CENTS": 1000,
    "SUPPLIER_UNIT_COST_CENTS": 600,
    "CASE_PACK_SIZE": 12,
    "CONFIRMED_DELIVERY_DATE": "2026-09-05T00:00:00Z",
    "ACTUAL_DELIVERY_DATE": "2026-09-05T00:00:00Z",
    "EVENT_VENUE": "Gym",
    "EVENT_WINDOW_START": "2026-09-06T15:00:00Z",
    "EVENT_WINDOW_END": "2026-09-06T18:00:00Z",
    "SLOT_CAPACITY": 2,
    "DISTRIBUTION_INSTANT": "2026-09-06T16:00:00Z",
    "INSIDE_RETURN_WINDOW": "2026-09-08T10:00:00Z",
    "RETURN_WINDOW_LAST_INSTANT": "2026-09-13T16:00:00Z",
    "AFTER_RETURN_WINDOW": "2026-09-14T00:00:00Z",
}
