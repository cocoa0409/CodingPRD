"""Domain thresholds and shared scenario constants from the PRD (§2 and §3)."""

THRESHOLDS = {
    # Shift duration bound: longer than zero and no more than 21600 seconds (§3.1)
    "SHIFT_MAX_SECONDS": 21600,
    # Reliability scoring (§3.1)
    "RELIABILITY_INITIAL": 100,
    "NO_SHOW_PENALTY": 15,
    "LEFT_EARLY_PENALTY": 5,
    "COMPLETION_BONUS": 2,
    "RELIABILITY_THRESHOLD": 40,
    # Waiver and induction validity windows (§3.1, §3.2)
    "WAIVER_VALID_DAYS": 365,
    "INDUCTION_VALID_DAYS": 365,
    # Suggested donation cap (§3.5)
    "SUGGESTION_CAP_CENTS": 5000,
}

# Triage priority scoring constants (§3.3)
TRIAGE_BASE_BY_CATEGORY = {"ELECTRONICS": 10, "TEXTILE": 5, "BIKE": 7}
TRIAGE_SEVERITY_WEIGHT = 8
TRIAGE_DIFFICULTY_WEIGHT = 2
TRIAGE_HAZARD_BONUS = 15

# Suggested donation category bases (§3.5)
DONATION_BASE_BY_CATEGORY = {"ELECTRONICS": 1500, "TEXTILE": 800, "BIKE": 1000}

# Shared clock / window constants used across fixtures
DEFAULT_CLOCK = "2026-06-01T09:00:00Z"
EVENT_START = "2026-06-01T08:00:00Z"
EVENT_END = "2026-06-01T16:00:00Z"
SHIFT_START = "2026-06-01T08:00:00Z"
SHIFT_END = "2026-06-01T12:00:00Z"
DEFAULT_INDUCTION = "2026-01-01T00:00:00Z"
