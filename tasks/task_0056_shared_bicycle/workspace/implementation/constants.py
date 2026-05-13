"""Domain thresholds — numeric constants used by the implementation.

Values are taken directly from PRD prose and SCAFFOLD calculation rules.
"""
from __future__ import annotations


# ----- Ride fare settlement (PRD §3.4) -----
PER_MIN_RATE_STD_CENTS = 30
PER_MIN_OVER_RATE_STD_CENTS = 50
PER_MIN_RATE_EBIKE_CENTS = 60
PER_MIN_OVER_RATE_EBIKE_CENTS = 100
SEGMENT_BREAK_MIN = 30
DAILY_CAP_STD_CENTS = 1500
DAILY_CAP_EBIKE_CENTS = 3000

# ----- Unlock pre-conditions (PRD §3.4) -----
MIN_UNLOCK_BALANCE_CENTS = 100

# ----- Monthly pass (PRD §3.3) -----
MONTHLY_PASS_DURATION_MINUTES = 43200
MONTHLY_PASS_PRICE_CENTS = 1500  # PRD does not pin this; pick a reasonable default.

# ----- Dispute window (PRD §3.10) -----
DISPUTE_WINDOW_MINUTES = 1440

# ----- Anomaly sweep (PRD §3.9) -----
LONG_STATIONARY_THRESHOLD_MIN = 1440
LOW_BATTERY_THRESHOLD_PCT = 20
SWEEP_DEFAULT_SLA_MINUTES = 1440

# ----- Loss-rate analytics (PRD §3.11) -----
ANOMALY_RATE_THRESHOLD = 0.05

# ----- On-shelf preconditions (PRD §3.2) -----
EBIKE_MIN_BATTERY_PCT = 20

# ----- Pagination (PRD §2.3) -----
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
