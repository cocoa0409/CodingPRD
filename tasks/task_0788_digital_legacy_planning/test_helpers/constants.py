"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# Readiness score targets (PRD 3.1)
COMPLETENESS = {
    "TARGET_ITEMS": 5,
    "TARGET_DIRECTIVES": 2,
    "TARGET_BENEFICIARIES": 3,
}

# Tier-derived values (PRD 2.9 / 3.7)
SEAT_LIMITS = {"FREE": 1, "PLUS": 5, "FAMILY": 10}
MONTHLY_FEE_CENTS = {"FREE": 0, "PLUS": 1200, "FAMILY": 2400}

# Quorum (PRD 3.6)
QUORUM_FRACTION = 0.5

# Time windows / durations
PERIOD_DAYS = 30                 # subscription billing period (PRD 3.7)
REFUND_PERIOD_DAYS = 30          # prorata denominator (PRD 3.7)
RELEASE_EXPIRY_DAYS = 14         # verify -> expires_at (PRD 3.6)
REMINDER_GRACE_DAYS = 30         # DUE -> OVERDUE grace window (PRD 3.8)
DEFAULT_REVIEW_INTERVAL_DAYS = 180
DEPUTY_TERM_BUFFER_DAYS = 7      # deputy term overlap guard (PRD 3.3)

# Logical clock default at server startup (PRD 2.5)
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"

# A stable base clock used by most fixtures.
BASE_CLOCK = "2026-06-01T00:00:00Z"
