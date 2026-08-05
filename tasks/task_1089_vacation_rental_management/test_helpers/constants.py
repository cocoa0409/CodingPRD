"""Domain thresholds — numeric constants from the PRD's calculations."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # re-exported for convenience

# Occupancy window (PRD §3.3)
WINDOW_HALF_DAYS = 15
WINDOW_TOTAL_DAYS = 30

# Dynamic nightly quote occupancy tiers and last-minute factor (PRD §3.3)
OCC_HIGH_PCT = 80
OCC_MID_PCT = 50
OCC_HIGH_MULT = 1.25
OCC_MID_MULT = 1.10
LAST_MINUTE_DAYS = 7
LAST_MINUTE_MULT = 0.85

# Cancellation refund thresholds in days-to-check-in (PRD §3.5)
FLEX_FULL_DAYS = 1
MOD_FULL_DAYS = 30
MOD_HALF_DAYS = 7
STRICT_FULL_DAYS = 60

# Work-order owner-approval threshold in cents (PRD §3.7)
OWNER_APPROVAL_THRESHOLD_CENTS = 50000

# Turnover crew buffer in minutes (PRD §3.6)
TURNOVER_BUFFER_MINUTES = 120

# Default clock at server startup (PRD §2.4)
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

__all__ = [
    "NON_EXISTENT_UUID",
    "WINDOW_HALF_DAYS",
    "WINDOW_TOTAL_DAYS",
    "OCC_HIGH_PCT",
    "OCC_MID_PCT",
    "OCC_HIGH_MULT",
    "OCC_MID_MULT",
    "LAST_MINUTE_DAYS",
    "LAST_MINUTE_MULT",
    "FLEX_FULL_DAYS",
    "MOD_FULL_DAYS",
    "MOD_HALF_DAYS",
    "STRICT_FULL_DAYS",
    "OWNER_APPROVAL_THRESHOLD_CENTS",
    "TURNOVER_BUFFER_MINUTES",
    "DEFAULT_CLOCK",
]
