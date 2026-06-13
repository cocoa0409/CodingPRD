"""Domain thresholds — numeric constants from the PRD calculations (§2.8, §3.6, §3.8)."""

# 3-way match tolerances (PRD §3.6)
THRESHOLDS = {
    "PRICE_TOLERANCE_PCT": 5,      # billed price may be up to floor(po_price*1.05)
    "QTY_TOLERANCE_PCT": 0,        # billed_qty may never exceed received_qty
    "AMOUNT_TOLERANCE_PCT": 2,     # invoice_total may be up to floor(matched_amount*1.02)
    # Vendor probation (PRD §2.9): enters PROBATION once exception_count rises above three.
    "VENDOR_PROBATION_THRESHOLD": 3,
}

# Composite-score weights (PRD §3.8)
SCORE_WEIGHTS = {
    "W_ON_TIME": 0.5,
    "W_PRICE": 0.3,
    "W_RELIABILITY": 0.2,
}

# Convenience defaults used by fixtures/tests.
TEST_DEFAULTS = {
    # Thresholds high enough that a single MANAGER approval suffices.
    "HIGH_APPROVAL_THRESHOLD": 100000000,
    "HIGH_DIRECTOR_THRESHOLD": 200000000,
    # A fixed clock instant used as the deterministic "now" in time-based setups.
    "DEFAULT_CLOCK": "2026-03-01T00:00:00Z",
}
