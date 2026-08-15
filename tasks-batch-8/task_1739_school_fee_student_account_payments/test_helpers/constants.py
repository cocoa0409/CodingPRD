"""Domain thresholds — numeric constants from PRD calculations (§2.6, §3)."""

# Logical clock default before any operator call (PRD §2.4).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Basis-point denominator for waiver/refund percentage math (PRD §2.6).
    "BP_DENOMINATOR": 10000,
    # Default-year policy knobs used across fixtures (PRD §3.1).
    "REFUND_FULL_DAYS": 2,
    "REFUND_PARTIAL_DAYS": 10,
    "PARTIAL_REFUND_PCT_BP": 5000,
    "PLAN_MIN_CENTS": 1000,
    "PLAN_MAX_INSTALLMENTS": 6,
    "WRITEOFF_MAX_CENTS": 100000,
    "AGING_INTERVAL_DAYS": 10,
    "GRAD_HOLD_THRESHOLD_CENTS": 5000,
}

TEST_DEFAULTS = {
    "FEE_AMOUNT": 3000,
    "PAYMENT_METHOD": "CARD",
}
