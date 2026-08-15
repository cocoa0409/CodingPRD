"""Domain thresholds and the fixed logical-clock constants (PRD 2.4, 3.x)."""

# Logical clock (PRD 2.4): the server's logical clock starts at exactly
# 2026-08-01T00:00:00Z before any clock-setting call is made.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"

# Canonical policy constants of the test property (PRD 3.1).
PROPERTY_DEFAULTS = {
    "late_fee_cap_cents": 5000,
    "nsf_fee_cap_cents": 3500,
    "monthly_waiver_cap_cents": 20000,
    "min_partial_payment_percent": 25,
    "collections_threshold_cents": 10000,
    "notice_cure_period_days": 10,
    "plan_cooling_off_days": 30,
    "plan_setup_fee_cents": 2500,
    "plan_setup_fee_threshold_cents": 20000,
}

# Plan schedule bounds (PRD 3.8).
MIN_INSTALLMENTS = 2
MAX_INSTALLMENTS = 12

# Payment acceptance (PRD 3.3): with the canonical 25% floor on a 200000-cent
# balance, the smallest acceptable partial payment is exactly 50000 cents.
PARTIAL_FLOOR_CENTS = 50000

# The note stamped on NSF reversal allocations (PRD 3.4).
NSF_REVERSAL_NOTE = "nsf-reversal"

# The literal recorded as creator of system-born charges (PRD 3.2).
SYSTEM_USER_ID = "system"
