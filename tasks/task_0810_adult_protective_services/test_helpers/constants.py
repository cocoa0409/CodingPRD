"""Domain thresholds — numeric constants drawn from the PRD's calculations."""

# Risk scoring (PRD Section 3.3)
RISK_WEIGHTS = {
    "isolation_level": 10,
    "cognitive_impairment_level": 12,
    "financial_vulnerability_level": 9,
    "caregiver_dependency_level": 8,
    "prior_report_count": 4,
}
PRIOR_REPORT_CAP = 5
SCORE_CAP = 100
HIGH_THRESHOLD = 70
MODERATE_THRESHOLD = 40

# Financial exposure / mandatory cross-report (PRD Sections 3.5 / 3.8)
MANDATORY_CROSS_REPORT_THRESHOLD_CENTS = 5_000_000

# Response-deadline SLAs in hours (PRD Section 3.1)
SLA_EMERGENCY_HOURS = 24
SLA_PRIORITY_HOURS = 72
SLA_ROUTINE_HOURS = 240

# Emergency placement cap (PRD Section 3.4)
PLACEMENT_EMERGENCY_CAP_HOURS = 72

# Freeze cool-down buffer (PRD Section 3.5)
FREEZE_COOLDOWN_HOURS = 24

# Default logical clock at server startup (PRD Section 2.5)
CLOCK_STARTUP = "2026-03-01T00:00:00Z"
