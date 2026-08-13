"""Domain thresholds and defaults — numeric constants from the PRD."""

CLOCK_START = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Program defaults (PRD section 3.1)
    "DEFAULT_PROMO_MIN_GAP_DAYS": 1,
    "DEFAULT_MIN_PAYOUT_CENTS": 5000,
    # Agreement commercial-term defaults (PRD section 3.1)
    "DEFAULT_TIER1_THRESHOLD_CENTS": 100000,
    "DEFAULT_TIER1_UPLIFT_PCT": 0.01,
    "DEFAULT_TIER2_THRESHOLD_CENTS": 200000,
    "DEFAULT_TIER2_UPLIFT_PCT": 0.02,
    "DEFAULT_MIN_MARGIN_PCT": 0.15,
    "DEFAULT_MAX_MARGIN_PCT": 0.40,
    "DEFAULT_FREE_ALLOWANCE_PCT": 0.01,
    "DEFAULT_SHRINK_SUSPEND_RATIO": 0.02,
    "DEFAULT_MARKDOWN_JOBBER_SHARE_PCT": 0.5,
    "DEFAULT_MARKDOWN_CAP_PCT_OF_GROSS": 0.08,
    "DEFAULT_SERVICE_FREQUENCY_DAYS": 7,
    # Margin promo drag (PRD section 3.9)
    "PROMO_DRAG_PCT": 0.01,
    "PROMO_DRAG_SHARE": 0.30,
    # Blended shrink valuation weights (PRD section 3.7)
    "BLENDED_COST_WEIGHT": 0.6,
    "BLENDED_RETAIL_WEIGHT": 0.4,
    # Settlement cadence lengths in days (PRD section 3.9)
    "WEEKLY_DAYS": 7,
    "BIWEEKLY_DAYS": 14,
    # Reorder cascade (PRD section 3.6)
    "REORDER_TARGET_MULTIPLIER": 2,
    # Markdown expiry fuse (PRD section 3.8)
    "MARKDOWN_EXPIRY_DAYS": 14,
    # Seasonal teardown penalty (PRD section 3.4)
    "TEARDOWN_GRACE_DAYS": 2,
    "TEARDOWN_PENALTY_PER_DAY_CENTS": 2500,
    "TEARDOWN_PENALTY_CAP_CENTS": 100000,
    # Pagination (PRD section 2.3)
    "DEFAULT_LIMIT": 10,
    "MAX_LIMIT": 100,
}

TEST_DEFAULTS = {
    "STORE_TOTAL_FACINGS": 50,
    "BASE_MARGIN_PCT": 0.25,
    "SHRINK_RETAILER_SHARE_PCT": 0.5,
    "RESTOCK_VALUE_CAP_CENTS": 50000,
    "JOBBER_COST_CENTS": 100,
    "MIN_RETAIL_CENTS": 150,
    "UNITS_PER_FACING": 12,
    "DIRECTIVE_PRICE_CENTS": 200,
    "DRIVER_ID": "drv-1",
    "AUDITOR_ID": "aud-1",
    "ADMIN_ID": "admin-1",
    "FINANCE_ID": "fin-1",
}
