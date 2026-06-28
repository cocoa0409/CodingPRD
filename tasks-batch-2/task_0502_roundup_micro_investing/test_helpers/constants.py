"""Domain thresholds — numeric constants from the PRD's calculations."""

# Basis-point denominator used for fee, rebate, market-value, and weight math.
BPS_DENOMINATOR = 10000

# IRA annual contribution cap in cents ($7,000) — PRD §3.7.
IRA_ANNUAL_CAP_CENTS = 700000

# Account sweep-threshold default and floor — PRD §3.2.
DEFAULT_SWEEP_THRESHOLD_CENTS = 500
MIN_SWEEP_THRESHOLD_CENTS = 100

# Referral redemption window — PRD §3.11 ("thirty days after created_at").
REFERRAL_WINDOW_DAYS = 30

# Referral qualification threshold — PRD §3.11 (lifetime_invested >= 500 cents).
REFERRAL_QUALIFY_MIN_INVESTED_CENTS = 500

# Recurring-contribution day-collision buffer — PRD §3.9 (+/-1 inclusive).
CONTRIBUTION_DAY_BUFFER = 1

# Permitted round-up multipliers — PRD §3.4.
ALLOWED_MULTIPLIERS = (1, 2, 3, 10)

# Logical clock startup default — PRD §2.10.
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"

# Pagination bounds — PRD §2.3.
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "min_offset": 0}
