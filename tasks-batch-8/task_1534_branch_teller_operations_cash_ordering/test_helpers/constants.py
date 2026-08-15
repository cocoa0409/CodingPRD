"""Domain thresholds — numeric constants from PRD §3."""

CTR_THRESHOLD_CENTS = 1_000_000            # strictly-greater trigger (PRD §3.6)
TELLER_TRANSACTION_LIMIT_CENTS = 500_000   # inclusive teller-direct withdrawal limit
MONEY_ORDER_MAX_CENTS = 100_000
CASHIERS_CHECK_FEE_CENTS = 800
MONEY_ORDER_FEE_CENTS = 200
NEXT_DAY_AVAILABILITY_CENTS = 20_000
LARGE_CHECK_FACE_CENTS = 500_000           # exactly this is still STANDARD
STANDARD_HOLD_DAYS = 2
LARGE_CHECK_HOLD_DAYS = 7
WAIVED_HOLD_DAYS = 1
ORDER_STEP_CENTS = 100_000
VAULT_CAPACITY_CENTS = 100_000_000
FORECAST_MIN_SAMPLES = 3
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

BRANCH_DEFAULTS = {
    "name": "Main St",
    "drawer_limit_cents": 1_000_000,
    "vault_cash_cents": 50_000_000,
    "over_short_investigation_threshold_cents": 1_000,
}
