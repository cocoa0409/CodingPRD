"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # PRD section 3.9: retainage rate 5% when pct_complete >= 0.5000, else 10%
    "RETAINAGE_RATE_HIGH": 0.10,
    "RETAINAGE_RATE_LOW": 0.05,
    "RETAINAGE_THRESHOLD": 0.5000,
    # PRD section 3.3: receive tolerance is +/-10% of ordered weight
    "MILL_TOLERANCE": 0.10,
    # PRD section 3.8: field-fix markup is fifteen percent of the subtotal
    "BACKCHARGE_MARKUP": 0.15,
    # PRD section 3.5: welder continuity window in whole days
    "WELDER_CONTINUITY_DAYS": 183,
    # PRD section 3.7: laydown slot buffer in whole days (closed at 2)
    "LAYDOWN_BUFFER_DAYS": 2,
    # PRD section 3.5: weld repair limit
    "WELD_REPAIR_LIMIT": 2,
}

TEST_DEFAULTS = {
    # The logical clock reads exactly this instant before it is ever set.
    "CLOCK_DEFAULT": "2026-08-01T00:00:00Z",
    "CONTRACT_VALUE_CENTS": 10_000_000,
    "ORDERED_WEIGHT_LBS": 100_000,
    "UNIT_PRICE_PER_CWT_CENTS": 4500,
    "TRAILER_CAPACITY_LBS": 20_000,
    "DELIVERY_DATE": "2026-09-01",
    "WELD_DATE": "2026-08-01",
    "QUAL_EXPIRES_ON": "2027-01-01",
    "PERIOD_LABEL": "2026-08",
}
