"""Domain thresholds — numeric constants from the PRD."""

# Deliverability breakpoints (PRD §2.11): inclusive.
WARN_RATE = 0.20
SUSPEND_RATE = 0.50

# Win-back discount percentage (PRD §3.5).
WIN_BACK_PERCENT_OFF = 0.20

# Billing period length in days (PRD §3.3, §3.4).
PERIOD_DAYS = 30

# Basis-points divisor for the platform-fee split (PRD §2.6).
BPS_DIVISOR = 10000

# Default platform fee when omitted at publication creation (PRD §3.1).
DEFAULT_PLATFORM_FEE_BPS = 1000

# Server logical clock startup default (PRD §2.10).
DEFAULT_CLOCK_UTC = "2026-03-01T00:00:00Z"

TEST_DEFAULTS = {
    "PLATFORM_FEE_BPS": 1000,
    "PLUS_PRICE": 1000,
    "PRO_PRICE": 2500,
}
