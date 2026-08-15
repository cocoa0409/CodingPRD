"""Domain thresholds and timetable constants stated in the PRD."""

# APH calculation (PRD §3.5)
T_YIELD = {"CORN": 180, "SOYBN": 50, "WHEAT": 65}
PLUG_YIELD = {"CORN": 135, "SOYBN": 37, "WHEAT": 49}
DISASTER_SUBSTITUTION_FACTOR = 0.65
OBSERVATION_YEARS = (2021, 2022, 2023, 2024, 2025)  # five trailing years for 2026

# PLC / ARC-CO payment calculation (PRD §3.8)
REFERENCE_PRICE = {"CORN": 4.10, "SOYBN": 9.00, "WHEAT": 5.50}
PLC_PAYMENT_FACTOR = 0.85
ARC_GUARANTEE_FACTOR = 0.86
ARC_CAP_FACTOR = 0.10
SEQUESTRATION_RATE = 0.057
LATE_FILED_FACTOR = 0.90

# Eligibility gates (PRD §3.1, §3.7)
AGI_LIMIT_CENTS = 90_000_000          # $900,000 statutory AGI limit, in cents
STANDARD_CAP_CENTS = 12_500_000       # $125,000.00 payment limitation
SPOUSE_CAP_CENTS = 25_000_000         # $250,000.00 with a qualifying spouse pair

# Disaster loss qualification ratio (PRD §3.9)
LOSS_THRESHOLD_RATIO = 0.35

# Logical-clock timetable (PRD §2.9, §3.3, §3.4)
STARTUP_CLOCK = "2026-08-01T00:00:00Z"          # server default before any set call
SAFE_CLOCK = "2026-02-01T00:00:00Z"             # election window open, acreage deadline far ahead
ACREAGE_DEADLINE = "2026-07-15T23:59:59Z"
LATE_FILE_CLOCK = "2026-07-20T00:00:00Z"        # inside the 30-day late window
PAST_LATE_WINDOW_CLOCK = "2026-08-15T23:59:59Z"  # beyond deadline + 30 days
ELECTION_DEADLINE = "2026-03-16T23:59:59Z"
PAST_ELECTION_WINDOW_CLOCK = "2026-04-01T00:00:00Z"

TEST_DEFAULTS = {
    "COUNTY_CODE": "019",
    "PROGRAM_YEAR": 2026,
    "COMMODITY": "CORN",
    "BASE_ACRES": 100.00,
    "AGI_CENTS": 50_000_000,
    "MY_PRICE_TRIGGERING": 3.50,
    "MY_PRICE_AT_REFERENCE": 4.10,
    "MY_PRICE_ABOVE_REFERENCE": 4.50,
    "ARC_BENCHMARK_REVENUE": 760.00,
    "ARC_COUNTY_ACTUAL_YIELD": 190.0,
}
