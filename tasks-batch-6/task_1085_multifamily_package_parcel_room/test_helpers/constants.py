"""Domain thresholds and policy defaults (from PRD §2 and §3.1 narratives)."""

# Property policy defaults (applied when the create-property payload omits them).
POLICY_DEFAULTS = {
    "overflow_threshold_pct": 0.85,
    "aging_days_standard": 10,
    "aging_days_perishable": 2,
    "perishable_hold_hours": 48,
    "holding_fee_grace_days": 3,
    "holding_fee_daily_cents": 150,
    "perishable_fee_multiplier": 2,
    "oversize_surcharge_cents": 500,
    "holding_fee_cap_cents": 5000,
    "return_staging_capacity": 25,
    "timezone": "UTC",
}

# Logical-clock startup instant (PRD §2.4): the server boots with the clock here.
CLOCK_START = "2026-05-01T00:00:00Z"

# Size-class rank ordering (PRD §2.6): a locker fits a package when its rank >= the package's.
SIZE_RANK = {"SMALL": 0, "MEDIUM": 1, "LARGE": 2, "OVERSIZE": 3}

# A deterministic, definitely-wrong six-character pickup code for negative-path tests.
WRONG_PICKUP_CODE = "000000"
