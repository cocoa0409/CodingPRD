"""Domain thresholds and well-known defaults from the PRD calculations and clock."""

# Logical clock default at server startup (PRD §2.10).
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# Spam scoring constants (PRD §3.4 / §3.6).
SPAM = {
    "BLOCKED_AREA_CODE_POINTS": 50,   # points added when area code is blocked
    "SCORE_CEILING": 100,             # final/provisional score is capped at 100
    "HUMAN_ENGAGEMENT_DROP": 30,      # subtracted at WRAP_UP if call reached IN_PROGRESS
    "DEFAULT_ANONYMOUS_PENALTY": 40,  # SpamRule.anonymous_penalty default
    "DEFAULT_SCORE_THRESHOLD": 70,    # SpamRule.spam_score_threshold default
}

# Per-minute rounding (PRD §2.9 / §3.7).
SECONDS_PER_MINUTE = 60

# Overage tiering (PRD §3.8).
DEFAULT_TIER2_THRESHOLD = 100

# Appointment reschedule bound (PRD §3.12).
RESCHEDULE_LIMIT = 3

# Escalation seniority gate (PRD §3.6): a senior agent has max_concurrent_calls >= 2.
SENIOR_MIN_CONCURRENT = 2
