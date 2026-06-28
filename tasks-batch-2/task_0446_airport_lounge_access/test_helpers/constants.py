"""Domain thresholds — numeric constants from the PRD's calculations and rules.

Generic NON_EXISTENT_UUID comes from the framework barrel export.
"""

# Hold time-to-live: hold_expires_at = held_at + 30 minutes (PRD §3.3).
HOLD_TTL_MINUTES = 30

# Day-pass time-to-live: valid_until = purchase + 24 hours (PRD §3.6).
DAY_PASS_TTL_HOURS = 24

# No-show strike threshold: at 3 strikes standing flips to SUSPENDED (PRD §3.8).
NO_SHOW_SUSPEND_THRESHOLD = 3

# GOLD-card per-line member fee discount multiplier (PRD §3.4).
MEMBER_FEE_DISCOUNT = 0.90

# Unlimited-allotment sentinel for included_visits_per_year (PRD §3.1).
UNLIMITED_VISITS_SENTINEL = -1

# Logical-clock startup default (PRD §2.4).
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# A syntactically valid UUID that resolves to no entity (for NOT_FOUND tests).
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

TEST_DEFAULTS = {
    "SETTLEMENT_RATE_CENTS": 1200,
    "GUEST_FEE_CENTS": 1000,
    "DAY_PASS_PRICE_CENTS": 4000,
    "OVERAGE_CHARGE_CENTS": 5000,
    "GUEST_CHARGE_CENTS": 2500,
    "CAPACITY": 50,
}
