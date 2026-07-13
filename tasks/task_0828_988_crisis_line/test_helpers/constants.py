"""Domain thresholds — numeric constants from the PRD scoring and aggregation rules."""

# Risk-screening score weights and banding thresholds (PRD §3.2).
RISK_SCORE = {
    "IDEATION_WEIGHT": 3,
    "PLAN_WEIGHT": 4,
    "MEANS_POINTS": 5,
    "PRIOR_WEIGHT": 2,
    "PRIOR_CAP": 3,
    "PROTECTIVE_WEIGHT": 2,
    "PROTECTIVE_CAP": 3,
    "IMMINENT_THRESHOLD": 20,
    "HIGH_THRESHOLD": 12,
    "MODERATE_THRESHOLD": 6,
}

# Dispatch priority scoring (PRD §3.5).
DISPATCH_PRIORITY = {
    "BAND_WEIGHT": {"IMMINENT": 100, "HIGH": 60, "MODERATE": 30, "LOW": 10},
    "WAIT_STEP_MINUTES": 10,
    "WAIT_STEP_POINTS": 4,
    "WAIT_STEP_CAP": 5,
    "REPEAT_BONUS": 15,
}

# Repeat-caller registry (PRD §3.1).
REPEAT_FLAG_THRESHOLD = 3

# Follow-up (PRD §3.8).
FOLLOWUP_DELAY_MINUTES = 1440
DEFAULT_MAX_ATTEMPTS = 3

# Team temporal buffer (PRD §3.5).
TEAM_TURNAROUND_MINUTES = 15

# Logical-clock startup default (PRD §2.4).
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"
