"""Domain thresholds and constants named in PRD §2.4, §2.10, §3.1, §3.3, §3.6, §3.7, §3.8."""

# Logical clock startup default (PRD §2.4: "the logical clock reads exactly
# 2026-08-01T00:00:00Z" before any clock-control call).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Appeal pipeline (PRD §3.1: "three is the system's maximum appeal level").
MAX_APPEAL_LEVEL = 3

# Work-queue scoring (PRD §2.10).
DOLLAR_POINT_DIVISOR_CENTS = 10000
DOLLAR_COMPONENT_CAP = 50
DEADLINE_HORIZON_DAYS = 30
DEADLINE_COMPONENT_CAP = 45
DEADLINE_DAILY_STEP = 1.5
LEVEL_BOOST_PER_LEVEL = 5
LEVEL_BOOST_CAP_LEVELS = 2
BUCKET_CRITICAL = 70.00
BUCKET_HIGH = 50.00
BUCKET_MEDIUM = 25.00

# Recovery projection (PRD §3.3).
DEFAULT_OVERTURN_RATE = 0.50
APPEAL_COST_CENTS = 5000

# Write-off approval hierarchy (PRD §3.6).
MANAGER_APPROVAL_LIMIT_CENTS = 2500000
WRITE_OFF_CEILING_CENTS = 10000000
STANDARD_TIER_MULTIPLIER = 1.0
ESCALATED_TIER_MULTIPLIER = 0.75

# Payer trailing overturn-rate review flag (PRD §3.1).
OVERTURN_RATE_FLOOR = 0.30
MIN_SAMPLE = 3

# Root-cause tasks (PRD §3.2 auto-task due date, §3.7 monitoring window).
AUTO_TASK_DUE_DAYS = 14
MONITORING_DAYS = 90

# Prevention scorecard weights and tier boundaries (PRD §3.8).
W_RECURRENCE = 50
W_PREVENTABLE = 30
W_OVERDUE = 20
TIER_EXCELLENT = 90.00
TIER_GOOD = 75.00
TIER_WATCH = 60.00

TEST_DEFAULTS = {
    "PAYER_NAME": "Payer A",
    "PLAN_TYPE": "COMMERCIAL",
    "DEFAULT_TIMELY_FILING_DAYS": 60,
    "POLICY_LEVEL_1_DAYS": 60,
    "POLICY_LEVEL_2_DAYS": 45,
    "RESPONSE_WINDOW_DAYS": 30,
    "CODE": "CO-16",
    "CATEGORY": "CODING",
    "DEPARTMENT": "CODING",
    "SERVICE_DATE": "2026-07-10",
    "REMITTANCE_RECEIVED_DATE": "2026-08-01",
    "POLICY_EFFECTIVE_FROM": "2026-01-01",
    "SPECIALIST_ID": "spec-1",
}
