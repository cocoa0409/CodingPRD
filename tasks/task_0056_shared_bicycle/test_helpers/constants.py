"""Domain thresholds — numeric constants used by tests.

Values are taken from PRD prose:
- PRD §2.5 fare arithmetic, §3.4 settlement formula
- PRD §3.3 monthly pass and minimum unlock balance
- PRD §3.9 sweep thresholds
- PRD §3.10 dispute window
- PRD §3.11 anomaly threshold

The reference implementation is the ground truth for any constant whose
exact value PRD prose explicitly states; tests use these to construct
boundary scenarios.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP


# ---------------------------------------------------------------------------
# Ride fare settlement (PRD §3.4)
# ---------------------------------------------------------------------------
PER_MIN_RATE_STD_CENTS = 30          # "30 cents per minute for the first 30 chargeable minutes"
PER_MIN_OVER_RATE_STD_CENTS = 50     # "50 cents per minute beyond"
PER_MIN_RATE_EBIKE_CENTS = 60        # "60 cents per minute for the first 30 chargeable minutes"
PER_MIN_OVER_RATE_EBIKE_CENTS = 100  # "100 cents per minute beyond"
SEGMENT_BREAK_MIN = 30               # "the segment threshold SEGMENT_BREAK_MIN of 30"
DAILY_CAP_STD_CENTS = 1500           # "The cap for a STANDARD bike is 1500 cents"
DAILY_CAP_EBIKE_CENTS = 3000         # "for an E_BIKE it is 3000 cents"
MIN_UNLOCK_BALANCE_CENTS = 100       # "the minimum unlock balance"

# ---------------------------------------------------------------------------
# Monthly pass (PRD §3.3)
# ---------------------------------------------------------------------------
MONTHLY_PASS_DURATION_MINUTES = 43200  # "exactly thirty days of platform time"

# ---------------------------------------------------------------------------
# Dispute (PRD §3.10)
# ---------------------------------------------------------------------------
DISPUTE_WINDOW_MINUTES = 1440  # "the current clock_minutes minus end_minute must not exceed 1440 minutes (one day)"

# ---------------------------------------------------------------------------
# Anomaly detection (PRD §3.9, §3.11)
# ---------------------------------------------------------------------------
LONG_STATIONARY_THRESHOLD_MIN = 1440  # "1440 minutes — one day"
LOW_BATTERY_THRESHOLD_PCT = 20        # "20%"
ANOMALY_RATE_THRESHOLD = 0.05         # "ANOMALY_RATE_THRESHOLD of 0.05"

# ---------------------------------------------------------------------------
# Bike on-shelf preconditions (PRD §3.2)
# ---------------------------------------------------------------------------
EBIKE_MIN_BATTERY_PCT = 20  # "battery_pct must be at least 20"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def round_half_up_4dp(value: float) -> float:
    """PRD §2.5: 'values exposed at the API boundary are rounded to four
    decimal places using half-up rounding.'"""
    quant = Decimal("0.0001")
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


__all__ = [
    "PER_MIN_RATE_STD_CENTS",
    "PER_MIN_OVER_RATE_STD_CENTS",
    "PER_MIN_RATE_EBIKE_CENTS",
    "PER_MIN_OVER_RATE_EBIKE_CENTS",
    "SEGMENT_BREAK_MIN",
    "DAILY_CAP_STD_CENTS",
    "DAILY_CAP_EBIKE_CENTS",
    "MIN_UNLOCK_BALANCE_CENTS",
    "MONTHLY_PASS_DURATION_MINUTES",
    "DISPUTE_WINDOW_MINUTES",
    "LONG_STATIONARY_THRESHOLD_MIN",
    "LOW_BATTERY_THRESHOLD_PCT",
    "ANOMALY_RATE_THRESHOLD",
    "EBIKE_MIN_BATTERY_PCT",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "round_half_up_4dp",
]
