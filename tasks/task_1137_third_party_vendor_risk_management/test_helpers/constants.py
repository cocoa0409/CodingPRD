"""Domain thresholds — numeric constants from the PRD's calculation sections.

Values below are copied from the PRD prose in §3.3, §3.7, §3.8, §3.9, §3.10,
and §3.14 (the same numbers the design indices pin their literals to).
"""

# Logical clock boot instant (PRD §2.8).
CLOCK_BOOT_ISO = "2026-05-01T00:00:00Z"

# PRD §3.3 — due-diligence aggregate score weights per tier, and outcome bands.
DD_TIER_WEIGHTS = {
    "TIER_1_CRITICAL": (0.25, 0.45, 0.30),
    "TIER_2_HIGH": (0.30, 0.40, 0.30),
    "TIER_3_STANDARD": (0.40, 0.35, 0.25),
    "TIER_4_LOW": (0.50, 0.25, 0.25),
}
DD_PASS_THRESHOLD = 75.00
DD_CONDITIONAL_THRESHOLD = 60.00

# PRD §3.10 — composite risk score weights, tier multipliers, cap.
SEV_WEIGHTS = {"SEV_1": 40, "SEV_2": 20, "SEV_3": 8, "SEV_4": 3}
OVERDUE_CYCLE_WEIGHT = 10
FAILED_BCP_WEIGHT = 15
TIER_MULTIPLIERS = {
    "TIER_1_CRITICAL": 1.5,
    "TIER_2_HIGH": 1.2,
    "TIER_3_STANDARD": 1.0,
    "TIER_4_LOW": 0.8,
}
COMPOSITE_SCORE_CAP = 100

# PRD §3.10 — tier posture thresholds (inclusive lower bound).
POSTURE_BREACH_THRESHOLD = 70
POSTURE_ESCALATED_THRESHOLD = 40
POSTURE_WATCH_THRESHOLD = 15

# PRD §3.7 — monitoring cadence in days per tier.
TIER_CADENCE_DAYS = {
    "TIER_1_CRITICAL": 90,
    "TIER_2_HIGH": 180,
    "TIER_3_STANDARD": 365,
    "TIER_4_LOW": 730,
}

# PRD §3.8 — remediation deadline windows in days per severity.
SEVERITY_WINDOW_DAYS = {"SEV_1": 7, "SEV_2": 30, "SEV_3": 90, "SEV_4": 180}

# PRD §3.9 — exit readiness deductions and pass floor.
EXIT_OPEN_INCIDENT_PENALTY = 50
EXIT_OPEN_PLAN_PENALTY = 20
EXIT_MISSING_EXIT_PLAN_PENALTY = 30
EXIT_PENDING_FP_PENALTY = 15
EXIT_OVERDUE_CYCLE_PENALTY = 10
EXIT_READINESS_PASS_THRESHOLD = 80.00

# PRD §3.14 — concentration breach share threshold (percent).
CONCENTRATION_BREACH_THRESHOLD_PCT = 25.00

# PRD §3.2 — DD review-round cap.
DD_REVIEW_ROUND_CAP = 3

# PRD §3.8 — incident reopen cap.
INCIDENT_REOPEN_CAP = 2

# PRD §3.4 — contract field ranges.
SLA_UPTIME_MIN = 90.000
SLA_UPTIME_MAX = 100.000
