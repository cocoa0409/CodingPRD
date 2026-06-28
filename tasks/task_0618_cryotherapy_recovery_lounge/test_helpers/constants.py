"""Domain thresholds — numeric constants from the PRD calculations and cycle rules."""

# Billing / membership cycle
BILLING_CYCLE_DAYS = 30
MAX_FREEZE_CYCLES = 3
FREEZE_FEE_CENTS = 1000

# Credit pack
PACK_VALIDITY_DAYS = 180
LIST_PRICE_PER_CREDIT_CENTS = 2195
INTRO_DISCOUNT_PCT = 0.30
PLATFORM_FEE_PCT = 0.08

# Cancellation / no-show fee
FREE_CANCEL_MINUTES = 240
BASE_FEE_CENTS = 2000
LATE_RATE_PER_HOUR_CENTS = 1500
FEE_CAP_CENTS = 5000

THRESHOLDS = {
    "BILLING_CYCLE_DAYS": BILLING_CYCLE_DAYS,
    "MAX_FREEZE_CYCLES": MAX_FREEZE_CYCLES,
    "FREEZE_FEE_CENTS": FREEZE_FEE_CENTS,
    "PACK_VALIDITY_DAYS": PACK_VALIDITY_DAYS,
    "LIST_PRICE_PER_CREDIT_CENTS": LIST_PRICE_PER_CREDIT_CENTS,
    "INTRO_DISCOUNT_PCT": INTRO_DISCOUNT_PCT,
    "PLATFORM_FEE_PCT": PLATFORM_FEE_PCT,
    "FREE_CANCEL_MINUTES": FREE_CANCEL_MINUTES,
    "BASE_FEE_CENTS": BASE_FEE_CENTS,
    "LATE_RATE_PER_HOUR_CENTS": LATE_RATE_PER_HOUR_CENTS,
    "FEE_CAP_CENTS": FEE_CAP_CENTS,
}

# Default plan configurations used across fixtures (cents / credits).
PLAN_BASE = {"tier": "BASE", "monthly_fee_cents": 9900, "monthly_credit_grant": 4, "rollover_cap": 0}
PLAN_PLUS = {"tier": "PLUS", "monthly_fee_cents": 16900, "monthly_credit_grant": 8, "rollover_cap": 4}
PLAN_ELITE = {"tier": "ELITE", "monthly_fee_cents": 24900, "monthly_credit_grant": 12,
              "rollover_cap": 4, "late_cancel_fee_waived": True}

# A path-shaped UUID that resolves to nothing.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

# Default server-startup logical clock instant (PRD Section 2.4).
SERVER_START_CLOCK = "2026-01-01T00:00:00Z"
