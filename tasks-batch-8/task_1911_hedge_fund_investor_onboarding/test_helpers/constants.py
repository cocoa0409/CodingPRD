"""Domain thresholds — numeric constants from PRD calculations."""

# Late-fee accrual: PRD §3.4 pins 5 basis points per day, per-day round-half-up.
LATE_FEE_DAILY_BPS = 5

# MFN rebate cap: PRD §3.5 pins the cap at 50% of the base fee.
REBATE_CAP_PCT = 0.5

# Series equalization factor rounding: round-half-up at final step.
DAYS_IN_YEAR = 365

# Default logical clock before any set_current_utc call (PRD §2.4).
DEFAULT_LOGICAL_CLOCK_UTC = "2026-08-01T00:00:00Z"
