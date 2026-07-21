"""Domain thresholds — numeric constants from the PRD calculations and rules."""

# Loyalty (PRD 2.7, 3.3)
POINTS_PER_DOLLAR = 1
SILVER_THRESHOLD = 500
GOLD_THRESHOLD = 2000

# Tier discount percentages applied to charter final settlement and service grand total.
TIER_DISCOUNT_PCT = {"BRONZE": 0.00, "SILVER": 0.05, "GOLD": 0.10}

# License voiding (PRD 3.3)
LICENSE_VOID_GRACE_DAYS = 7

# Charter cancellation refund (PRD 3.6)
CANCEL_FULL_REFUND_HOURS = 48
CANCEL_PARTIAL_REFUND_PCT = 0.50

# Service order grand total tax (PRD 3.8)
TAX_RATE = 0.08

# Guide turnaround buffer (PRD 3.4)
TURNAROUND_BUFFER_MINUTES = 60

# Logical clock default at server startup (PRD 2.4)
DEFAULT_CLOCK_UTC = "2026-07-01T00:00:00Z"

THRESHOLDS = {
    "POINTS_PER_DOLLAR": POINTS_PER_DOLLAR,
    "SILVER_THRESHOLD": SILVER_THRESHOLD,
    "GOLD_THRESHOLD": GOLD_THRESHOLD,
    "LICENSE_VOID_GRACE_DAYS": LICENSE_VOID_GRACE_DAYS,
    "CANCEL_FULL_REFUND_HOURS": CANCEL_FULL_REFUND_HOURS,
    "TAX_RATE": TAX_RATE,
    "TURNAROUND_BUFFER_MINUTES": TURNAROUND_BUFFER_MINUTES,
}
