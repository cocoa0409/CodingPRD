"""Domain thresholds and shared instants from the PRD's calculation rules."""

THRESHOLDS = {
    # Child age-band derivation (PRD §3.4)
    "DAYS_PER_YEAR": 365.25,
    "MAX_AGE_YEARS": 19,
    # Backfill selector (PRD §3.8)
    "WAIT_DAY_CAP": 30,
    "AGE_BASELINE": 18,
    # Distribution slot lane buckets (PRD §3.9)
    "LANE_BUCKET_CAPACITY": 4,
    "BUCKET_MINUTES": 30,
    # Adoption pledge confirmation window (PRD §3.6)
    "PLEDGE_CONFIRM_HOURS": 72,
    # SeasonSettings defaults (PRD §2.11)
    "DEFAULT_LATE_DONOR_GRACE_HOURS": 0,
    "MAX_LATE_DONOR_GRACE_HOURS": 72,
    "DEFAULT_MAJOR_DONOR_THRESHOLD_CENTS": 50000,
}

# Canonical logical-clock instants used across fixtures. The server starts its
# logical clock at 2026-08-01T00:00:00Z (PRD §2.5).
CLOCK = {
    "SERVER_START": "2026-08-01T00:00:00Z",
    "DURING_INTAKE": "2026-09-15T00:00:00Z",
    "AFTER_RETURN_DEADLINE": "2026-12-11T00:00:00Z",
    "DISTRIBUTION_DAY_EARLY": "2026-12-18T09:00:00Z",
}

# Standard campaign window used by most fixtures (PRD §2.5 calendar windows).
CAMPAIGN_DEFAULTS = {
    "season_year": 2026,
    "intake_open_at": "2026-09-01T00:00:00Z",
    "intake_close_at": "2026-10-15T00:00:00Z",
    "gift_return_deadline": "2026-12-10T00:00:00Z",
    "distribution_date": "2026-12-18T00:00:00Z",
    "max_children_per_family": 6,
    "max_gift_value_cents": 20000,
    "min_gift_value_cents": 2000,
    "backfill_budget_cents": 0,
}

# Distribution-day event window used by slot fixtures.
EVENT_WINDOW = {
    "start_at": "2026-12-18T09:00:00Z",
    "end_at": "2026-12-18T17:00:00Z",
}
