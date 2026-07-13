"""Domain thresholds — the numeric constants the PRD's formulas and ceilings name."""

THRESHOLDS = {
    # PRD §3.5 — the regular allowance for the day is eight hours (480 minutes),
    # and overtime is priced at time-and-a-half.
    "OVERTIME_THRESHOLD_MINUTES": 480,
    "OVERTIME_MULTIPLIER": 1.5,
    # PRD §3.5 — no one may log more than ten hours in a single UTC day.
    "MAX_DAILY_MINUTES": 600,
    # PRD §3.4 — the agency contracts for a maximum of three revision rounds.
    "MAX_REVISION_ROUNDS": 3,
    # PRD §3.8 — media commission tiers and clamps.
    "MEDIA_TIER1_CENTS": 5_000_000,
    "MEDIA_TIER2_CENTS": 20_000_000,
    "MIN_COMMISSION_CENTS": 50_000,
    "MAX_COMMISSION_CENTS": 2_500_000,
    # PRD §3.8 — volume discount tiers and the admin fee.
    "DISCOUNT_TIER1_CENTS": 10_000_000,
    "DISCOUNT_TIER2_CENTS": 25_000_000,
    "ADMIN_FEE_PCT": 0.03,
}

# PRD §2.5 — before any caller has moved it, the logical clock reads exactly this.
DEFAULT_LOGICAL_CLOCK = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "CLOCK": "2026-06-01T00:00:00Z",
    "RATE_JUNIOR_CENTS_PER_HOUR": 12_000,
    "RATE_SENIOR_CENTS_PER_HOUR": 20_000,
    "RATE_DIRECTOR_CENTS_PER_HOUR": 32_000,
    "COST_RATE_JUNIOR": 3_000,
    "COST_RATE_SENIOR": 6_000,
    "COST_RATE_DIRECTOR": 9_000,
    "STANDARD_DAILY_CAPACITY_MINUTES": 480,
    "MARKUP_PCT": 0.175,
    "LABOR_CAP_CENTS": 4_000_000,
    "SOW_EFFECTIVE_START": "2026-06-01",
    "SOW_EFFECTIVE_END": "2026-09-01",
    "PERIOD_START": "2026-06-01",
    "PERIOD_END": "2026-07-01",
}
