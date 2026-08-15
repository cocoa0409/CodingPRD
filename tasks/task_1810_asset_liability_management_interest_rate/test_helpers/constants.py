"""Domain thresholds and shared constants from the PRD (§2.4, §3.3, §3.5–§3.7)."""

# Logical clock startup instant (PRD §2.4): the clock reads exactly this value
# at server startup and never falls back to wall-clock time.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_PERIOD_MONTH = "2026-08"

# Backtest deviation tolerances per assumption domain, in percentage points
# (PRD §3.7).
BACKTEST_TOLERANCE_PCT = {
    "PREPAYMENT": 3.0,
    "DEPOSIT_DECAY": 2.0,
    "DEPOSIT_BETA": 10.0,
}

# The six regulatory presets map to fixed instantaneous shocks in basis points
# (PRD §3.3).
REGULATORY_PRESET_SHOCK_BPS = {
    "REG_UP_400": 400,
    "REG_UP_300": 300,
    "REG_UP_200": 200,
    "REG_DOWN_200": -200,
    "REG_DOWN_300": -300,
    "REG_DOWN_400": -400,
}
ALL_PRESET_CODES = list(REGULATORY_PRESET_SHOCK_BPS.keys())

# Hedge effectiveness acceptance bands (PRD §3.6).
DOLLAR_OFFSET_MIN_RATIO = 0.8000
DOLLAR_OFFSET_MAX_RATIO = 1.2500
REGRESSION_MIN_R_SQUARED = 0.80
REGRESSION_MIN_SLOPE = 0.80
REGRESSION_MAX_SLOPE = 1.25
REGRESSION_MIN_SAMPLE_COUNT = 12

# An OPEN breach escalates once the clock reaches or passes the instant five
# days after its created_at (PRD §3.5).
BREACH_ACK_DEADLINE_DAYS = 5

# Canonical worked-example book ("Book1") used across the calculation tests.
BOOK1_CURVE_BPS = 400
BOOK1_LOAN = {
    "category": "LOAN",
    "balance_cents": 100_000_000,
    "rate_bps": 600,
    "scheduled_runoff_pct": 20.0,
    "is_prepayment_eligible": True,
    "duration_years": 3.0,
}
BOOK1_SECURITY = {
    "category": "SECURITY",
    "balance_cents": 50_000_000,
    "rate_bps": 400,
    "scheduled_runoff_pct": 0.0,
    "duration_years": 4.0,
}
BOOK1_DEPOSIT = {
    "category": "DEPOSIT",
    "deposit_segment": "RETAIL_NONMATURITY",
    "balance_cents": 80_000_000,
    "rate_bps": 50,
    "scheduled_runoff_pct": 0.0,
    "duration_years": 0.5,
}
BOOK1_BORROWING = {
    "category": "BORROWING",
    "balance_cents": 40_000_000,
    "rate_bps": 450,
    "scheduled_runoff_pct": 25.0,
    "duration_years": 2.0,
}

# Canonical approved assumption parameters for the worked-example book.
BOOK1_PREPAYMENT_PARAMS = {"base_cpr_pct": 10.0, "prepay_sensitivity_per_100bps": 2.0}
BOOK1_DECAY_PARAMS = {"base_annual_decay_pct": 5.0, "surge_decay_per_100bps": 1.0}
BOOK1_BETA_PARAMS = {"up_beta_pct": 40.0, "down_beta_pct": 20.0, "lag_months": 6}
