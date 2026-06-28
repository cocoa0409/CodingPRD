"""Domain thresholds — numeric constants from the PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# A syntactically valid UUID that no created resource will ever match.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"

# Default server logical clock at startup (before any /_clock/set_current_utc).
CLOCK_DEFAULT_UTC = "2026-04-01T00:00:00Z"

# Profile-strength scoring (PRD Section 3.1).
PROFILE = {
    "GPA_MAX": 4.0,
    "GPA_WEIGHT": 40,
    "SAT_MIN": 400,
    "SAT_RANGE": 1200,
    "SAT_WEIGHT": 30,
    "TIER1_WEIGHT": 1.0,
    "TIER2_WEIGHT": 0.7,
    "TIER3_WEIGHT": 0.4,
    "TIER4_WEIGHT": 0.2,
    "RESUME_CAP": 30,
}

# Admit-probability scoring (PRD Section 3.4).
ADMIT_PROB = {
    "GAP_HIGH": 100,
    "MULT_HIGH": 1.6,
    "MULT_FLOOR": 0.5,
    "STRENGTH_PIVOT": 50,
    "STRENGTH_WEIGHT": 0.3,
}

# School classification thresholds (PRD Section 3.2).
CLASSIFICATION = {
    "SAFETY_THRESHOLD": 0.60,
    "REACH_THRESHOLD": 0.20,
}

# List-balance lock (PRD Section 3.2).
LIST_LOCK = {
    "MIN_SAFETY": 1,
    "MIN_TOTAL": 3,
    "MAX_ED": 1,
}

# Scholarship coordination (PRD Section 3.6).
COORDINATION_CAP_CENTS = 4_000_000

# Appointment overlap buffer in minutes (PRD Section 3.8).
APPOINTMENT_BUFFER_MIN = 15

# Appeal window in days (PRD Section 3.9).
APPEAL_WINDOW_DAYS = 30

# Pagination defaults (PRD Section 2.3).
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}

# Common test values.
TEST_DEFAULTS = {
    "COVERAGE_START": "2026-04-01T00:00:00Z",
    "COVERAGE_END": "2027-06-01T00:00:00Z",
    "DEADLINE": "2027-01-01T00:00:00Z",
}
