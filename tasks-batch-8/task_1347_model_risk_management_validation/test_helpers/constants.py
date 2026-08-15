"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# Risk tier boundaries (PRD §3.1)
TIER_1_MIN = 70
TIER_2_MIN = 40
SCORE_CAP = 100

# Findings penalty weights per severity (PRD §3.1)
FINDINGS_PENALTY = {"CRITICAL": 10, "HIGH": 5, "MEDIUM": 2, "LOW": 1}

# Complexity / scope / exposure points (PRD §3.1)
COMPLEXITY_POINTS = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
SCOPE_POINTS = {"SINGLE_DESK": 0, "MULTI_DESK": 1, "ENTERPRISE": 2}

# Remediation deadline formula (PRD §3.6)
BASE_DAYS = {"LOW": 90, "MEDIUM": 60, "HIGH": 30, "CRITICAL": 14}
TIER_MULTIPLIER = {"TIER_1": 1.0, "TIER_2": 1.5, "TIER_3": 2.0}
MONITORING_URGENCY_DEDUCTION = 5
MIN_DAYS = 7
MAX_DAYS = 365
ESCALATION_GRACE_DAYS = 7

# Revalidation calendar (PRD §3.1 / §3.3)
REVALIDATION_MONTHS = {"TIER_1": 6, "TIER_2": 12, "TIER_3": 24}
MAJOR_CHANGE_REVALIDATION_MONTHS = 3

# Monitoring escalation (PRD §3.7)
CONSECUTIVE_BREACH_LIMIT = 3

# Vendor transparency approval gate (PRD §3.5)
VENDOR_MIN_COMPLETENESS = 70

# Logical clock startup default (PRD §2.5)
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "BUSINESS_UNIT": "Risk",
    "EXPOSURE_AMOUNT": 100,
    "DECLARED_COMPLEXITY": "LOW",
    "USAGE_SCOPE": "SINGLE_DESK",
    "METRIC_NAME": "psi",
    "METRIC_DIRECTION": "ABOVE_IS_BREACH",
    "METRIC_THRESHOLD": 0.25,
}
