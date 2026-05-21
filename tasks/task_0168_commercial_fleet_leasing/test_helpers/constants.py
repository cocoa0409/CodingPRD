"""Domain thresholds — numeric constants from PRD calculations.

All monetary values are integer cents per PRD §2.7:
"All money in this system is stored and transmitted as integer cents —
there are no floating-point dollar amounts anywhere in the schema."
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Overage tier breakpoints / multipliers — PRD §3.6.
# Tier 1: [0, 500)            -> rate = overage_rate_cents_per_mile
# Tier 2: [500, 2000)         -> rate * 12500 / 10000  (1.25x)
# Tier 3: [2000, +inf)        -> rate * 15000 / 10000  (1.50x)
# ---------------------------------------------------------------------------
TIER1_BREAK: int = 500
TIER2_BREAK: int = 2000
TIER2_MULT_BPS: int = 12500  # 1.25x
TIER3_MULT_BPS: int = 15000  # 1.50x


# ---------------------------------------------------------------------------
# Collision settlement — PRD §3.7.
# Cap at $2,500 = 250,000 cents; good-telematics discount 25% (2500 bps).
# ---------------------------------------------------------------------------
DEDUCTIBLE_CAP_CENTS: int = 250_000
GOOD_TELEMATICS_DISCOUNT_BPS: int = 2500  # 25%


# ---------------------------------------------------------------------------
# Collision revision rounds — PRD §3.7.
# "revision_round must be strictly less than the configured maximum
# revision rounds at the moment of the request" — chosen value: 2.
# ---------------------------------------------------------------------------
MAX_REVISION_ROUNDS: int = 2


# ---------------------------------------------------------------------------
# IFTA per-jurisdiction rates (cents per gallon) — PRD §3.9.
# ---------------------------------------------------------------------------
IFTA_RATES: dict = {
    "CA": 87,
    "TX": 20,
    "NY": 45,
    "IL": 47,
    "FL": 36,
    "OH": 47,
    "PA": 75,
    "GA": 32,
    "WA": 49,
    "AZ": 26,
}


# ---------------------------------------------------------------------------
# Lessee balance thresholds — PRD §2.9.
# "when the balance reaches or exceeds the suspend threshold, the
# lessee is suspended; when the balance reaches or exceeds the
# (strictly higher) default threshold ..."
# The PRD pins suspend at the level produced by collisions/overages
# in the difficulty-design scenarios; for tests we choose values that
# leave headroom for non-default scenarios.
# ---------------------------------------------------------------------------
SUSPEND_THRESHOLD_CENTS: int = 100_000  # $1,000
DEFAULT_THRESHOLD_CENTS: int = 200_000  # $2,000


# ---------------------------------------------------------------------------
# Dispute window — PRD §3.6.
# "the current clock must be at or before the row's created_at plus the
# dispute window in days (a non-strict upper bound — equality is
# permitted)" — chosen value: 14 days.
# ---------------------------------------------------------------------------
DISPUTE_WINDOW_DAYS: int = 14


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Field bounds — PRD §3.1, §3.2, §3.3
# ---------------------------------------------------------------------------
LEGAL_NAME_MIN: int = 1
LEGAL_NAME_MAX: int = 120
DOT_NUMBER_MIN_DIGITS: int = 6
DOT_NUMBER_MAX_DIGITS: int = 8
VIN_LEN: int = 17
MODEL_YEAR_MIN: int = 2000
MODEL_YEAR_MAX: int = 2030
MONTHLY_MILEAGE_ALLOWANCE_MIN: int = 1000
MONTHLY_MILEAGE_ALLOWANCE_MAX: int = 15000
OVERAGE_RATE_MIN: int = 5
OVERAGE_RATE_MAX: int = 100
LEASE_MAX_MONTHS: int = 60
CARD_PAN_LAST4_LEN: int = 4
CARD_MONTHLY_LIMIT_MIN: int = 50_000
CARD_MONTHLY_LIMIT_MAX: int = 1_000_000
TXN_GALLONS_MAX: float = 200.0
TXN_AMOUNT_MAX_CENTS: int = 100_000
PERIOD_YEAR_MIN: int = 2000
PERIOD_YEAR_MAX: int = 2099
PERIOD_MONTH_MIN: int = 1
PERIOD_MONTH_MAX: int = 12
IFTA_QUARTER_MIN: int = 1
IFTA_QUARTER_MAX: int = 4


# ---------------------------------------------------------------------------
# Supported jurisdictions — PRD §3.1, §3.3 (closed list of 10 US states)
# ---------------------------------------------------------------------------
SUPPORTED_JURISDICTIONS: tuple = (
    "CA", "TX", "NY", "IL", "FL", "OH", "PA", "GA", "WA", "AZ",
)


# ---------------------------------------------------------------------------
# Test defaults
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    "LESSEE_LEGAL_NAME": "Test Carrier LLC",
    "VEHICLE_BASELINE_MILES": 0,
    "INITIAL_CLOCK_ISO": "2026-03-01T00:00:00.000Z",
    "DEFAULT_MILEAGE_ALLOWANCE": 1000,
    "DEFAULT_OVERAGE_RATE": 25,
    "DEFAULT_CARD_LIMIT_CENTS": 100_000,
}


__all__ = [
    "TIER1_BREAK", "TIER2_BREAK",
    "TIER2_MULT_BPS", "TIER3_MULT_BPS",
    "DEDUCTIBLE_CAP_CENTS", "GOOD_TELEMATICS_DISCOUNT_BPS",
    "MAX_REVISION_ROUNDS",
    "IFTA_RATES",
    "SUSPEND_THRESHOLD_CENTS", "DEFAULT_THRESHOLD_CENTS",
    "DISPUTE_WINDOW_DAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "LEGAL_NAME_MIN", "LEGAL_NAME_MAX",
    "DOT_NUMBER_MIN_DIGITS", "DOT_NUMBER_MAX_DIGITS",
    "VIN_LEN",
    "MODEL_YEAR_MIN", "MODEL_YEAR_MAX",
    "MONTHLY_MILEAGE_ALLOWANCE_MIN", "MONTHLY_MILEAGE_ALLOWANCE_MAX",
    "OVERAGE_RATE_MIN", "OVERAGE_RATE_MAX",
    "LEASE_MAX_MONTHS",
    "CARD_PAN_LAST4_LEN",
    "CARD_MONTHLY_LIMIT_MIN", "CARD_MONTHLY_LIMIT_MAX",
    "TXN_GALLONS_MAX", "TXN_AMOUNT_MAX_CENTS",
    "PERIOD_YEAR_MIN", "PERIOD_YEAR_MAX",
    "PERIOD_MONTH_MIN", "PERIOD_MONTH_MAX",
    "IFTA_QUARTER_MIN", "IFTA_QUARTER_MAX",
    "SUPPORTED_JURISDICTIONS",
    "TEST_DEFAULTS",
]
