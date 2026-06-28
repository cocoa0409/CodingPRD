"""Domain thresholds — numeric constants from the PRD finance and scoring rules."""

# Finance schedule (PRD §3.7)
THRESHOLDS = {
    "DOWN_TIER_CENTS": 600000,   # tuition >= $6,000 -> 20% down, else 10%
    "DOWN_PCT_HIGH": 0.20,
    "DOWN_PCT_LOW": 0.10,
    "MONTHLY_RATE": 0.01,        # 1% simple interest per month
}

# Skills weighted-score weights (PRD §3.5)
SCORE_WEIGHTS = {
    "W_PRE_TRIP": 0.30,
    "W_BASIC_CONTROL": 0.30,
    "W_ROAD": 0.40,
}

DEFAULT_SKILLS_PASS_THRESHOLD = 80
DEFAULT_TURNAROUND_BUFFER_MINUTES = 30

# Default server logical clock at startup (PRD §3.8)
DEFAULT_CLOCK_UTC = "2026-04-01T00:00:00Z"

# Common test values
TEST_DEFAULTS = {
    "TUITION_CENTS": 700000,
    "FUTURE_EXPIRY": "2027-01-01T00:00:00Z",
}
