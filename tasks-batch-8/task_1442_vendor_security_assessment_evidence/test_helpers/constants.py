"""Domain thresholds and constants from the PRD's calculation rules (§3).

Values here are verbatim from PRD prose: tier response windows (§3.3),
score thresholds (§3.4/§3.7), evidence scoring constants (§3.5), risk-score
bases and modifiers (§3.8), pull-forward deltas (§3.8), cadences (§3.1),
and deadline offsets (§3.9).
"""

# PRD §2.6: logical clock startup default.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# PRD §3.3: response window in days by tier.
TIER_RESPONSE_WINDOW_DAYS = {"TIER_1": 45, "TIER_2": 30, "TIER_3": 21, "TIER_4": 14}

# PRD §3.4/§3.7: tier pass thresholds.
TIER_PASS_THRESHOLD = {"TIER_1": 60.0, "TIER_2": 70.0, "TIER_3": 80.0, "TIER_4": 90.0}

# PRD §3.4: questionnaire scoring.
ANSWER_SCORE = {"YES": 1.0, "PARTIAL": 0.5, "NO": 0.0}
REVISION_PENALTY_PCT = 0.05
REVISION_PENALTY_CAP = 20.0

# PRD §3.5: evidence scoring.
EVIDENCE_KIND_BASE = {
    "SOC2_TYPE2": 100.0,
    "ISO27001": 95.0,
    "SOC2_TYPE1": 80.0,
    "PENTEST": 70.0,
    "OTHER": 50.0,
}
GAP_PENALTY_MAX = 30.0
STANDARD_GAP_WINDOW_DAYS = 365   # TIER_1 / TIER_2
STRICT_GAP_WINDOW_DAYS = 180     # TIER_3 / TIER_4
COVERAGE_GAP_REJECT_DAYS = 180   # gap strictly greater than this fails review
SEVERITY_DEDUCTION = {"CRITICAL": 25.0, "HIGH": 15.0, "MEDIUM": 8.0, "LOW": 3.0}

# PRD §3.7: composite weights.
COMPOSITE_W_QUESTIONNAIRE = 0.40
COMPOSITE_W_EVIDENCE = 0.60

# PRD §3.1: default reassessment cadences (months).
DEFAULT_CADENCE_MONTHS = {"TIER_1": 36, "TIER_2": 24, "TIER_3": 12, "TIER_4": 6}

# PRD §3.8: vendor risk score bases by posture and alert modifiers.
POSTURE_RISK_BASE = {
    "ONBOARDING": 50.0,
    "ASSESSING": 60.0,
    "APPROVED": 20.0,
    "CONDITIONAL": 45.0,
    "SUSPENDED": 85.0,
    "OFFBOARDING": 70.0,
    "OFFBOARDED": 10.0,
}
ALERT_RISK_MODIFIER = {"HIGH": 5.0, "CRITICAL": 10.0}
ACCEPTED_EXCEPTION_RISK = 3.0
EXPIRY_IMMINENT_RISK = 8.0
EXPIRY_IMMINENT_WINDOW_DAYS = 30

# PRD §3.8: escalation pull-forward deltas (days).
PULL_FORWARD_CRITICAL_DAYS = 14
PULL_FORWARD_HIGH_DAYS = 30
PULL_FORWARD_ACCEPTANCE_EXPIRY_DAYS = 30

# PRD §3.9: offboarding deadlines.
OFFBOARDING_DEADLINE_DAYS = 90
OFFBOARDING_SLIP_EXTENSION_DAYS = 30

# Classification triples whose rank-sum fallback lands in each tier (PRD §3.1).
TIER_PROFILES = {
    # INTERNAL(1) + READ_ONLY(1) + LOW(0) = 2 -> TIER_1
    "TIER_1": {"data_sensitivity": "INTERNAL", "access_level": "READ_ONLY", "criticality": "LOW"},
    # CONFIDENTIAL(2) + READ_ONLY(1) + MEDIUM(1) = 4 -> TIER_2
    "TIER_2": {"data_sensitivity": "CONFIDENTIAL", "access_level": "READ_ONLY", "criticality": "MEDIUM"},
    # CONFIDENTIAL(2) + OPERATOR(2) + HIGH(2) = 6 -> TIER_3
    "TIER_3": {"data_sensitivity": "CONFIDENTIAL", "access_level": "OPERATOR", "criticality": "HIGH"},
    # REGULATED(3) + PRIVILEGED(3) + MISSION_CRITICAL(3) = 9 -> TIER_4
    "TIER_4": {"data_sensitivity": "REGULATED", "access_level": "PRIVILEGED", "criticality": "MISSION_CRITICAL"},
}

TEST_DEFAULTS = {
    "LEGAL_NAME": "Acme Vendor",
    "CONTACT_EMAIL": "contact@example.com",
    "CONTACT_NAME": "Vendor Contact",
    "SUBMITTED_BY": "vc@example.com",
    "ISSUED_BY": "AuditCo",
}
