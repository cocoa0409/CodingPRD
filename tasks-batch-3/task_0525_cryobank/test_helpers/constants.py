"""Domain thresholds — numeric constants from PRD calculations (§3.5, §3.7, §3.9)."""

# Storage billing (PRD §3.7)
ANNUAL_RATE_CENTS_PER_VIAL = 42000   # $420.00 per vial per full period
BILLING_PERIOD_DAYS = 365
GRACE_DAYS = 30

# Reservation hold window (PRD §3.5)
HOLD_TTL_DAYS = 5

# Dewar maintenance overlap buffer (PRD §3.9)
SETTLE_BUFFER_HOURS = 24

# Logical clock startup default (PRD §3.11)
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    "ANNUAL_RATE_CENTS_PER_VIAL": ANNUAL_RATE_CENTS_PER_VIAL,
    "BILLING_PERIOD_DAYS": BILLING_PERIOD_DAYS,
    "GRACE_DAYS": GRACE_DAYS,
    "HOLD_TTL_DAYS": HOLD_TTL_DAYS,
    "SETTLE_BUFFER_HOURS": SETTLE_BUFFER_HOURS,
}
