"""Domain thresholds and shared values from the PRD (§2.5, §2.7, §3.5, §3.8)."""

# PRD §3.8 discrepancy credit tiers.
LATE_PENALTY_PCT = 0.25
EARLY_PENALTY_PCT = 0.0

# PRD §3.8 audience delivery weighting.
SPOT_WEIGHT = 1000

# PRD §3.5 commercial separation: at least one other spot must stand between
# two same-category spots in a break's airing order.
MIN_SEPARATION_POSITIONS = 1

# PRD §3.3 / §3.4 allowed spot lengths.
SPOT_LENGTHS = (15, 30, 60, 120)

# PRD §2.5: the logical clock reads exactly this instant at startup.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Broadcast-week anchors used throughout the suite. 2026-08-03 is a Monday;
# ISO weekday numbers map to the dates of that week.
WEEK_ONE_START = "2026-08-03"
WEEK_TWO_START = "2026-08-10"
WEEKDAY_DATE_WEEK_ONE = {
    1: "2026-08-03",  # Monday
    2: "2026-08-04",  # Tuesday
    3: "2026-08-05",  # Wednesday
    4: "2026-08-06",  # Thursday
    5: "2026-08-07",  # Friday
    6: "2026-08-08",  # Saturday
    7: "2026-08-09",  # Sunday
}
WEEKDAY_DATE_WEEK_TWO = {
    1: "2026-08-10",
    2: "2026-08-11",
    3: "2026-08-12",
    4: "2026-08-13",
    5: "2026-08-14",
    6: "2026-08-15",
    7: "2026-08-16",
}

TEST_DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 100_000_000,
    "GROSS_RATE_CENTS": 5_000,
    "TOTAL_SECONDS": 60,
    "FLIGHT_START": "2026-08-03",
    "FLIGHT_END": "2026-08-09",
}
