"""Domain thresholds — numeric constants drawn from the PRD calculations and rules."""

THRESHOLDS = {
    # Balances / late penalty
    "LATE_PENALTY_PCT": 0.25,
    # Scofflaw & enforcement eligibility
    "SCOFFLAW_AMOUNT_THRESHOLD_CENTS": 50000,
    "SCOFFLAW_COUNT_THRESHOLD": 5,
    "BOOT_COUNT_THRESHOLD": 5,
    "TOW_AMOUNT_THRESHOLD_CENTS": 100000,
    # Release fee
    "BOOT_FEE_CENTS": 15000,
    "TOW_FEE_CENTS": 25000,
    "ADMIN_FEE_CENTS": 5000,
    "DAILY_STORAGE_RATE_CENTS": 4000,
    "MAX_STORAGE_DAYS": 30,
    # Payment plan
    "PAYMENT_PLAN_MAX_INSTALLMENTS": 12,
    "PAYMENT_PLAN_MIN_DOWN_PCT": 0.10,
    # Hardship waiver
    "HARDSHIP_TIER_1_PCT": 0.50,
    "HARDSHIP_TIER_2_PCT": 1.00,
    # Temporal windows (days)
    "DISPUTE_WINDOW_DAYS": 21,
    "COLLECTIONS_MIN_AGE_DAYS": 90,
}

# Derived, precomputed release-fee references (integer cents).
BOOT_RELEASE_FEE_CENTS = THRESHOLDS["BOOT_FEE_CENTS"] + THRESHOLDS["ADMIN_FEE_CENTS"]  # 20000
TOW_BASE_FEE_CENTS = THRESHOLDS["TOW_FEE_CENTS"] + THRESHOLDS["ADMIN_FEE_CENTS"]        # 30000

# Logical-clock startup default.
CLOCK_START = "2026-05-01T00:00:00Z"
DEFAULT_ISSUED_AT = "2026-05-01T00:00:00Z"
DEFAULT_DUE_AT = "2026-12-31T00:00:00Z"
