"""Domain thresholds — numeric constants from PRD §2.5-§2.8 and §3."""

# PRD §2.5 — logical clock startup default.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# PRD §2.7 — per-tier budget caps (inclusive) and flat bond requirements, cents.
ULB_CAP_CENTS = 30_000_000
MODIFIED_LOW_CAP_CENTS = 75_000_000
LOW_BUDGET_CAP_CENTS = 250_000_000
TIER_CAPS = {
    "ULTRA_LOW_BUDGET": ULB_CAP_CENTS,
    "MODIFIED_LOW_BUDGET": MODIFIED_LOW_CAP_CENTS,
    "LOW_BUDGET": LOW_BUDGET_CAP_CENTS,
}
BOND_REQUIRED_BY_TIER = {
    "ULTRA_LOW_BUDGET": 2_500_000,
    "MODIFIED_LOW_BUDGET": 5_000_000,
    "LOW_BUDGET": 10_000_000,
    "BASIC": 25_000_000,
}

# PRD §3.1 — bounded info-request loop.
MAX_REVIEW_ROUNDS = 3

# PRD §3.4 — per-tier per-department minimum staffing (inclusive boundary).
MIN_CREW_BY_TIER_DEPT = {
    "ULTRA_LOW_BUDGET": {"CAMERA": 1, "GRIP_ELECTRIC": 1, "SOUND": 1},
    "MODIFIED_LOW_BUDGET": {"CAMERA": 2, "GRIP_ELECTRIC": 2, "SOUND": 1},
    "LOW_BUDGET": {"CAMERA": 3, "GRIP_ELECTRIC": 2, "SOUND": 2},
    "BASIC": {"CAMERA": 4, "GRIP_ELECTRIC": 3, "SOUND": 2},
}

# PRD §3.5 — work-log penalty constants.
MEAL_WINDOW_MINUTES = 360
MEAL_PENALTY_UNIT_MINUTES = 30
TURNAROUND_HOURS_BY_TIER = {
    "ULTRA_LOW_BUDGET": 12,
    "MODIFIED_LOW_BUDGET": 12,
    "LOW_BUDGET": 10,
    "BASIC": 10,
}

# PRD §3.7 — contribution dues: rate numerators and daily wage caps per tier.
CONTRIBUTION_RATE_NUM = {
    "ULTRA_LOW_BUDGET": 17,
    "MODIFIED_LOW_BUDGET": 18,
    "LOW_BUDGET": 19,
    "BASIC": 20,
}
DAILY_WAGE_CAP_CENTS = {
    "ULTRA_LOW_BUDGET": 100_000,
    "MODIFIED_LOW_BUDGET": 150_000,
    "LOW_BUDGET": 250_000,
    "BASIC": 500_000,
}

# PRD §3.6 — grievance filing window.
FILING_WINDOW_DAYS = 30

# PRD §3.7 — audit assessment penalty multiplier (110/100).
AUDIT_PENALTY_RATE_NUM = 110

# PRD §2.8 — open-grievance posture threshold (inclusive).
GRIEVANCE_RESTRICTION_THRESHOLD = 2

# Common test defaults.
DEFAULT_BUDGET_CENTS = 20_000_000
ULB_BOND_CENTS = BOND_REQUIRED_BY_TIER["ULTRA_LOW_BUDGET"]
