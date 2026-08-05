"""Domain thresholds — numeric constants from the PRD calculations and gates."""

# Risk score weights (§3.2)
RISK_SCORE = {
    "W_PF": 4,    # points per prior failure-to-appear
    "W_PC": 2,    # points per pending charge
    "W_EMP": 3,   # UNEMPLOYED (FULL only)
    "W_RES": 3,   # UNSTABLE residence (FULL only)
    "W_SUB": 5,   # substance flag (FULL only)
}

# Recommended-level thresholds (§3.2), inclusive (>=)
LEVEL_THRESHOLDS = {
    "T_MED": 8,
    "T_MAX": 16,
}

# Supervision-fee rates (§3.8)
FEE = {
    "DAILY_SUPERVISION_CENTS": 300,
    "EM_DAILY_CENTS": 650,
    "PER_TEST_CENTS": 2500,
    "ADMIN_FEE_PCT": 0.075,
}

# Cumulative violation score / escalation (§3.7)
VIOLATION = {
    "VIOLATION_WINDOW_DAYS": 90,
    "ESCALATION_THRESHOLD": 10,
    "ESCALATED_CHECKIN_DAYS": 7,
    "SEVERITY_POINTS_MINOR": 3,
    "SEVERITY_POINTS_MODERATE": 6,
    "SEVERITY_POINTS_MAJOR": 10,
}

# Drug-test slot length (§3.8)
TEST_SLOT_MINUTES = 30

# Failure-to-appear grace period in hours (§3.6)
FTA_GRACE_HOURS = 2

# Server startup default logical clock (§2.5)
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
