"""Domain thresholds and numeric constants from PRD calculations."""

# Logical-clock defaults (PRD: server startup clock is exactly this instant)
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# substantiation_score (PRD §3.7)
W_EVIDENCE = 0.25
W_INTERVIEW = 0.15
C_LOW = 0.00
C_MEDIUM = 0.15
C_HIGH = 0.30
W_ADMISSION = 0.10
SUBSTANTIATED_THRESHOLD = 0.70

# discipline_severity_index (PRD §3.8)
SEVERITY_WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
PRIOR_STEP = 0.25
PRIOR_CAP = 3
ADJ_STEP = 5
ADJ_CAP = 2

# pattern_risk_score (PRD §3.15)
RECENCY_FLOOR = 0.20
SPREAD_STEP = 0.25
SPREAD_CAP = 2
VOLUME_STEP = 0.5
PATTERN_BASE = 10
TIER_HIGH = 70
TIER_MEDIUM = 40

# evidence_review_effort_minutes (PRD §3.4)
MINUTES_PER_MB = 2
OVERHEAD = 1.15

# case_priority_score (PRD §3.10)
ESCALATION_BOOST = 15
DISCLOSURE_URGENCY_BOOST = 10
DISCLOSURE_URGENCY_WINDOW_DAYS = 7
TIER_URGENT = 40
TIER_ELEVATED = 20

# Disclosure cooling-off (PRD §3.11)
COOLING_OFF_HOURS = 72

TEST_DEFAULTS = {
    "LEAD_INVESTIGATOR_ID": "inv-lead-1",
    "DRAFTER_ID": "inv-1",
    "APPROVER_ID": "mgr-1",
    "FINALIZER_ID": "mgr-9",
    "HR_ID": "hr-1",
    "GC_ID": "gc-1",
    "CLO_ID": "clo-1",
    "AUDITOR_ID": "aud-1",
    "EMPLOYEE_REF": "EMP-100",
    "INTERVIEWER_ID": "inv-9",
    "OWNER_REF": "own-1",
}
