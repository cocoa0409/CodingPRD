"""Domain thresholds — numeric constants named in the PRD's calculation rules."""

THRESHOLDS = {
    # PRD §3.4: defect_pct at or below 5 leaves adjusted cost at provisional.
    "DEFECT_TOLERANCE_PCT": 5,
    # PRD §3.9: first 8 hours straight time, 1.5x beyond; $15.00/hr piece floor.
    "OT_THRESHOLD_HOURS": 8,
    "OT_MULTIPLIER": 1.5,
    "MIN_WAGE_DOLLARS": 15.00,
    # PRD §3.7: $25.00 per pallet deposit; 2% early-pay discount; 5-day window.
    "PALLET_DEPOSIT_CENTS": 2500,
    "EARLY_PAY_DISCOUNT_PCT": 0.02,
    "DISCOUNT_DAYS": 5,
    # PRD §3.1: PACA terms cap without a special agreement; default terms.
    "TERMS_LIMIT_DAYS": 30,
    "DEFAULT_TERMS_DAYS": 10,
    # PRD §3.7: PAST_DUE invoice becomes TRUST_CLAIMED more than 30 days past due.
    "TRUST_CLAIM_DAYS": 30,
    # PRD §3.1: default cold-chain tolerance.
    "DEFAULT_MAX_VIOLATION_MINUTES": 60,
}

TEST_DEFAULTS = {
    # Logical clock value used by most setups (PRD §2.4 default is midnight;
    # setups advance it to 08:00 so same-day activity is unambiguous).
    "CLOCK_START": "2026-05-01T08:00:00Z",
    "DEFAULT_CLOCK": "2026-05-01T00:00:00Z",
    "MARKET_DATE": "2026-05-01",
    "DELIVERY_DATE": "2026-05-02",
    "LOW_PRICE": 8.00,
    "HIGH_PRICE": 12.00,
    "UNIT_PRICE": 10.00,
    "LOT_QUANTITY": 100,
    "GRADE": "US1",
    "CREDIT_LIMIT": 1000000,
}
