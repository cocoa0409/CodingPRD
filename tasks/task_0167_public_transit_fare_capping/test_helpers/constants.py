"""Domain thresholds — numeric constants from PRD calculations.

All monetary values are integer cents per PRD §2.8:
"All monetary quantities ... are stored and exchanged as integer cents.
The only step in any calculation that introduces fractional cents is
the post-discount per-leg base fare in the fare formula and the
proportional FSA share in the refund split; in both cases the result is
rounded half-up to the nearest whole cent before being used."
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Fare / cap constants — PRD §2.9, §3.5
# ---------------------------------------------------------------------------
BASE_FARE_CENTS: int = 275
DAILY_CAP_CENTS: int = 600
WEEKLY_CAP_CENTS: int = 3300

# Default per PRD §1: monthly_contribution_cap_cents default 31500 (US IRS
# Transit FSA monthly limit reference). The PRD §3.1 says the employer's
# monthly_contribution_cap_cents is an integer "which must be zero or
# greater"; tests supply this value explicitly.
DEFAULT_MONTHLY_FSA_CAP_CENTS: int = 31_500

# Discount rates per PRD §3.2.
REDUCED_FARE_DISCOUNT_RATE: float = 0.50
LOW_INCOME_DISCOUNT_RATE: float = 0.60

# Transfer / incomplete sweep — PRD §3.5, §3.6.
TRANSFER_WINDOW_MINUTES: int = 120
INCOMPLETE_FORCED_MINUTES: int = 180

# Low-income eligibility — PRD §3.3: "the threshold for eligibility is
# three million cents (that is, thirty thousand US dollars)".
LOW_INCOME_THRESHOLD_CENTS: int = 3_000_000

# Low-income expiry — PRD §3.3: "the low-income expiry sweep walks every
# verification whose `approved_at` plus three hundred sixty-five days is
# at or before the current server time".
LOW_INCOME_ACTIVE_DAYS: int = 365

# Idempotency key constraint — PRD §3.5.
MIN_IDEMPOTENCY_KEY_LEN: int = 1
MAX_IDEMPOTENCY_KEY_LEN: int = 64


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Computed fare values (handy for clarity in tests) — derived from
# BASE_FARE_CENTS and the discount rates with round_half_up:
#   REDUCED_FARE  fare = round_half_up(275 * 0.50) = 138
#   LOW_INCOME    fare = round_half_up(275 * 0.60) = 165
# ---------------------------------------------------------------------------
REDUCED_FARE_BASE_CENTS: int = 138
LOW_INCOME_BASE_CENTS: int = 165


# ---------------------------------------------------------------------------
# Test defaults — values used by factories when no override is given.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    "RIDER_FULL_NAME": "Test Rider",
    "EMPLOYER_LEGAL_NAME": "Acme Transit Co.",
    "CARD_TOPUP_DEFAULT": 1000,
    "FSA_CONTRIB_DEFAULT": 1000,
    "INITIAL_CLOCK_ISO": "2026-05-20T08:00:00.000Z",
}


__all__ = [
    "BASE_FARE_CENTS",
    "DAILY_CAP_CENTS",
    "WEEKLY_CAP_CENTS",
    "DEFAULT_MONTHLY_FSA_CAP_CENTS",
    "REDUCED_FARE_DISCOUNT_RATE",
    "LOW_INCOME_DISCOUNT_RATE",
    "TRANSFER_WINDOW_MINUTES",
    "INCOMPLETE_FORCED_MINUTES",
    "LOW_INCOME_THRESHOLD_CENTS",
    "LOW_INCOME_ACTIVE_DAYS",
    "MIN_IDEMPOTENCY_KEY_LEN",
    "MAX_IDEMPOTENCY_KEY_LEN",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "REDUCED_FARE_BASE_CENTS",
    "LOW_INCOME_BASE_CENTS",
    "TEST_DEFAULTS",
]
