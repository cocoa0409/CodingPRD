"""Domain thresholds — numeric constants from PRD §3 calculation rules."""

# Reconciliation tolerance: |reported - expected| <= 100 cents matches (PRD §3.7).
VARIANCE_TOLERANCE_CENTS = 100

# Producer suspension circuit: PENDING chargeback outstanding total strictly
# greater than 500000 cents suspends the producer (PRD §3.8).
SUSPEND_THRESHOLD_CENTS = 500000

# 1099 generation threshold: cash-basis year total >= 60000 cents (PRD §3.9).
FORM_1099_THRESHOLD_CENTS = 60000

# Override cap: 25% of the base entry's booked amount (PRD §3.3).
MAX_OVERRIDE_SHARE_BPS = 2500

# Commission year length used by booking and earned-month math (PRD §3.3, §3.6).
COMMISSION_YEAR_MONTHS = 12

# Invoice due date = policy effective_date + 30 calendar days (PRD §3.3).
INVOICE_DUE_DAYS = 30

# Grace period: nonpayment cancellation at oldest delinquent due date + 30 days
# (PRD §3.5).
GRACE_DAYS = 30

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Shared defaults for fixtures.
DEFAULT_SCHEDULE_EFFECTIVE_FROM = "2026-01-01"
DEFAULT_POLICY_EFFECTIVE_DATE = "2026-08-01"
DEFAULT_STATEMENT_PERIOD_START = "2026-08-01"
DEFAULT_STATEMENT_PERIOD_END = "2026-08-31"

TEST_DEFAULTS = {
    "PREMIUM_CENTS": 2400000,
    "RATE_BPS": 5000,
}
