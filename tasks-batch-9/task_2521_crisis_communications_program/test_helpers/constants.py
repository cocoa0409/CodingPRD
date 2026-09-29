"""Literal constants declared by the PRD.

Every value here is copied from the PRD narrative; nothing is inferred.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

STARTUP_CLOCK = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Rounding (PRD §2.7)
# ---------------------------------------------------------------------------

MONEY_DP = 2
FINE_DP = 4

# ---------------------------------------------------------------------------
# Issue signal escalation score (PRD §3.2)
# ---------------------------------------------------------------------------

CREDIBILITY_MULTIPLIER = {"A": 1.00, "B": 0.85, "C": 0.60}
SENTIMENT_PENALTY_SCALE = 30
CHANNEL_TYPE_BUMP = {"MEDIA": 8, "SOCIAL": 4, "REGULATORY": 15}
REGULATORY_FLAG_BUMP = 12
ESCALATION_SCORE_CAP = 100.00
ESCALATION_SCORE_THRESHOLD = 70.00

# ---------------------------------------------------------------------------
# Severity tiers (PRD §3.3)
# ---------------------------------------------------------------------------

SEVERITY_BAND_FLOOR = {"SEV1": 90.00, "SEV2": 70.00, "SEV3": 50.00}
SEVERITY_TIER_POINTS = {"SEV1": 100, "SEV2": 75, "SEV3": 50, "SEV4": 25}

# Holding-statement SLA window in minutes, keyed by severity tier (PRD §3.3).
SLA_WINDOW_MINUTES = {"SEV1": 30, "SEV2": 60, "SEV3": 180, "SEV4": 480}

# ---------------------------------------------------------------------------
# Containment priority (PRD §3.3)
# ---------------------------------------------------------------------------

EXPOSURE_COMPONENT_CAP = 100.00
CONTAINMENT_TIER_WEIGHT = 0.7
CONTAINMENT_EXPOSURE_WEIGHT = 0.3
AMPLIFICATION_BAND_FLOOR = {"HIGH": 80.00, "MEDIUM": 55.00}
AMPLIFICATION_RATE = {"HIGH": 0.20, "MEDIUM": 0.10, "LOW": 0.05}
CONTAINMENT_PRIORITY_CAP = 150.00

# Claim states that contribute virality to the exposure component.
EXPOSURE_CLAIM_STATES = [
    "DETECTED",
    "TRIAGED",
    "PLATFORM_ESCALATED",
    "CORRECTION_ISSUED",
]

# ---------------------------------------------------------------------------
# Approval quorum and review windows (PRD §3.5)
# ---------------------------------------------------------------------------

REVIEW_WINDOW_MINUTES = {"SEV1": 15, "SEV2": 30, "SEV3": 90, "SEV4": 240}
QUORUM_ROLE_ORDER = ["INCIDENT_LEAD", "LEGAL_COUNSEL", "EXEC_SPONSOR"]
DECISION_AUTHORITY_RANK = {"FULL": 0, "LIMITED": 1}
REVISION_ROUND_LIMIT = 3

# ---------------------------------------------------------------------------
# Stakeholder notices (PRD §3.6)
# ---------------------------------------------------------------------------

AUDIENCE_SEQUENCE_RANK = {
    "EMPLOYEE": 1,
    "CUSTOMER": 2,
    "REGULATOR": 3,
    "INVESTOR": 4,
    "MEDIA": 5,
}
AUDIENCE_REACH_WEIGHT = {
    "EMPLOYEE": 1.00,
    "CUSTOMER": 1.25,
    "REGULATOR": 1.50,
    "INVESTOR": 1.75,
    "MEDIA": 2.00,
}
REACH_CONTRIBUTION_DIVISOR = 1000
STATUTORY_OVERRIDE_DELAY_HOURS = 2
AUTO_STATEMENT_WITHDRAWN = "AUTO_STATEMENT_WITHDRAWN"

# ---------------------------------------------------------------------------
# Prepared materials (PRD §3.1)
# ---------------------------------------------------------------------------

READINESS_SCORE_START = 100.00
READINESS_DECAY_PER_DAY = 2.50
READINESS_READY_FLOOR = 60.00
READINESS_SCORE_FLOOR = 0.00

# ---------------------------------------------------------------------------
# Media interviews (PRD §3.7)
# ---------------------------------------------------------------------------

INTERVIEW_BUFFER_MINUTES = 30
MIN_ANTICIPATED_QUESTION_COUNT = 8
MIN_HIGH_RISK_ANSWERS_APPROVED_COUNT = 3

# ---------------------------------------------------------------------------
# Misinformation claims (PRD §3.8)
# ---------------------------------------------------------------------------

PLATFORM_ESCALATION_VIRALITY_FLOOR = 60.00
DEFAULT_MAX_CONCURRENT_CORRECTIONS = 1
MIN_MAX_CONCURRENT_CORRECTIONS = 1
MAX_MAX_CONCURRENT_CORRECTIONS = 5

# ---------------------------------------------------------------------------
# Resolution and post-crisis review (PRD §3.9)
# ---------------------------------------------------------------------------

FINAL_SEVERITY_PEAK_WEIGHT = 0.6
FINAL_SEVERITY_AVERAGE_WEIGHT = 0.4
EXPOSURE_FACTOR_DIVISOR = 100
EXPOSURE_FACTOR_CAP = 0.50
EFFICACY_BONUS_MAX = 2.50
DEFAULT_REPUTATION_INDEX_BEFORE = 50.00
AUTO_CASCADE_INCIDENT_RESOLVED = "AUTO_CASCADE_INCIDENT_RESOLVED"

# ---------------------------------------------------------------------------
# Field length ceilings (PRD §2.4 / §3.x)
# ---------------------------------------------------------------------------

MAX_FULL_NAME_LEN = 120
MAX_ORG_TITLE_LEN = 120
MAX_CHANNEL_NAME_LEN = 120
MAX_HEADLINE_LEN = 240
MAX_INCIDENT_TITLE_LEN = 160
MAX_STATEMENT_BODY_LEN = 4000
MAX_MATERIAL_TITLE_LEN = 160
MAX_OUTLET_NAME_LEN = 160
MAX_CLAIM_TEXT_LEN = 500
