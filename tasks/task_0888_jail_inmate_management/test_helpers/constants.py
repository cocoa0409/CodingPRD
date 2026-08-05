"""Domain thresholds — numeric constants from PRD calculations."""

# Good-time credit (PRD §3.8)
STATUTORY_RATE = 0.10
EARNED_CAP_RATE = 0.20
ACCRUAL_RATE_BY_LEVEL = {"MIN": 0.25, "MED": 0.15, "MAX": 0.05}

# Classification scoring (PRD §3.2)
SEVERITY_POINTS = {"FELONY": 30, "MISDEMEANOR": 10, "INFRACTION": 5}
HISTORY_PER_PRIOR = 6
HISTORY_CAP = 30
BEHAVIOR_PER_UPHELD = 15
MED_THRESHOLD = 25
MAX_THRESHOLD = 55

# Commissary order pricing (PRD §2.9 / §3.4)
TAX_RATE = 0.0725
SERVICE_FEE_CENTS = 25

# Visitation spacing (PRD §3.6)
VISIT_BUFFER_MINUTES = 30

# Logical clock default (PRD §2.8)
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"
