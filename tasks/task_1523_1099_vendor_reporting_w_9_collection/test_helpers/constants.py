"""Domain thresholds and defaults from the PRD.

All money is integer cents. Rates are basis points (2400 = 24 percent).
"""

# PRD §2.6: backup withholding rate default and conversion divisor.
BACKUP_WITHHOLDING_RATE_BPS = 2400
BPS_DIVISOR = 10000

# PRD §3.1: TaxYear threshold defaults.
DEFAULT_EFILING_THRESHOLD_COUNT = 10
DEFAULT_NEC_REPORTABLE_THRESHOLD_CENTS = 60000
DEFAULT_MISC_REPORTABLE_THRESHOLD_CENTS = 60000

# PRD §2.3: pagination defaults.
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
MIN_PAGE_LIMIT = 1

# Standard TaxYear window used by most fixtures (calendar 2025, half-open).
DEFAULT_TAX_YEAR = 2025
DEFAULT_PERIOD_START = "2025-01-01T00:00:00Z"
DEFAULT_PERIOD_END_EXCLUSIVE = "2026-01-01T00:00:00Z"
DEFAULT_RECIPIENT_COPY_DEADLINE = "2026-01-31T00:00:00Z"

# PRD §2.4: logical clock default at server startup.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"


def withheld_for(amount_cents: int, rate_bps: int = BACKUP_WITHHOLDING_RATE_BPS) -> int:
    """PRD §2.6 / §3.4 pinned rounding: round_half_up(amount_cents * rate_bps / 10000).

    Computed per payment, never over an aggregate.
    """
    numerator = amount_cents * rate_bps
    # round half up for non-negative values
    return (numerator * 2 + BPS_DIVISOR) // (2 * BPS_DIVISOR)


def quarter_of(payment_date: str) -> int:
    """PRD §3.4: withholding quarter is the payment month divided by three,
    rounded up to a whole number, yielding one through four."""
    month = int(payment_date[5:7])
    return (month + 2) // 3
