"""Domain thresholds — numeric constants from PRD calculations (section 3)."""

THRESHOLDS = {
    # Orders above this grand total on a po_required corporate account route to review (PRD 3.4).
    "PO_REVIEW_GRAND_TOTAL_CENTS": 1_000_000,
    # Oversize surcharge tiers (PRD 3.7).
    "OVERSIZE_BASE_CENTS": 8900,
    "OVERSIZE_ZONE_STEP_CENTS": 2500,
    "OVERSIZE_ZONE_STEP_DISTANCE": 4,
    "HEAVY_LINE_THRESHOLD_LBS": 150,
    "HEAVY_LINE_CENTS": 5000,
    # Return window in calendar days (PRD 3.8).
    "RETURN_WINDOW_DAYS": 30,
    # Custom-print over/under tolerance band, inclusive (PRD 3.4).
    "MAX_TOLERANCE_PCT": 20,
}

CALC = {
    "CUSTOM_PRINT_SURCHARGE_PCT": 0.15,
    "PALLET_REBATE_PCT": 0.03,
    "CUSTOM_RESTOCK_PCT": 0.15,
    "PROVISIONAL_UPLIFT": 1.10,
}

TEST_DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 100_000_000,
    "BASE_PRICE_CENTS": 1000,
    "STOCK_ON_HAND": 500,
    "CLOCK_MON_AM": "2026-08-03T10:00:00Z",
}
