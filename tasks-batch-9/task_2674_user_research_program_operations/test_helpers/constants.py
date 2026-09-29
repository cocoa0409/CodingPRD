"""Domain constants for the User Research Program Operations API.

Every value here is taken verbatim from the PRD; nothing is invented.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"
SECONDS_PER_DAY = 86400

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# ---------------------------------------------------------------------------
# Priority score (PRD 3.1)
# ---------------------------------------------------------------------------
DECISION_POINTS = {
    "IRREVERSIBLE": 40.0,
    "REVERSIBLE": 22.0,
}
GAP_POINTS = {
    "NONE": 0.0,
    "PARTIAL": 12.0,
    "FULL": 25.0,
}
REACH_BUCKET_USERS = 10000
REACH_POINTS_PER_BUCKET = 5.0
REACH_POINTS_CAP = 30.0

URGENCY_NEAR_DAYS = 14
URGENCY_NEAR_MULTIPLIER = 1.30
URGENCY_MID_DAYS = 45
URGENCY_MID_MULTIPLIER = 1.15
URGENCY_FAR_MULTIPLIER = 1.00

PRIORITY_SCORE_CAP = 100.0

# ---------------------------------------------------------------------------
# Method recommendation (PRD 3.1)
# ---------------------------------------------------------------------------
RECOMMENDED_METHOD_BY_QUESTION_TYPE = {
    "DISCOVERY": "INTERVIEW",
    "EVALUATIVE": "USABILITY_TEST",
    "BEHAVIORAL_LONGITUDINAL": "DIARY_STUDY",
    "MEASUREMENT": "SURVEY",
}
MEASUREMENT_UNDERPOWERED_USER_COUNT = 5000
MEASUREMENT_UNDERPOWERED_METHOD = "INTERVIEW"

# ---------------------------------------------------------------------------
# Reframing loop and decision lock (PRD 3.1)
# ---------------------------------------------------------------------------
MAX_REVISION_ROUNDS = 2
DECISION_LOCK_CONFIDENCE_THRESHOLD = 0.60

# ---------------------------------------------------------------------------
# Participant posture and pool posture (PRD 3.2)
# ---------------------------------------------------------------------------
SUPPRESSION_STRIKE_THRESHOLD = 2
POOL_CLOSED_UTILIZATION = 0.95
POOL_RESTRICTED_UTILIZATION = 0.80
SUPPRESSION_RATIO_THRESHOLD = 0.50

# ---------------------------------------------------------------------------
# Reservation surcharge tiers (PRD 3.4)
# ---------------------------------------------------------------------------
SURCHARGE_TIER_MID_UTILIZATION = 0.50
SURCHARGE_TIER_MID_PERCENT = 0.05
SURCHARGE_TIER_HIGH_UTILIZATION = 0.80
SURCHARGE_TIER_HIGH_PERCENT = 0.10
SURCHARGE_TIER_LOW_PERCENT = 0.00

# ---------------------------------------------------------------------------
# Concurrent fielding capacity (PRD 3.3)
# ---------------------------------------------------------------------------
POOL_CONCURRENT_FIELDING_LIMIT = 2

# ---------------------------------------------------------------------------
# Screen score (PRD 3.5)
# ---------------------------------------------------------------------------
SCREEN_SEGMENT_POINTS = 40.0
SCREEN_LOCALE_POINTS = 20.0
SCREEN_TARGET_ANSWER_POINTS_PER_HIT = 15.0
SCREEN_TARGET_ANSWER_POINTS_CAP = 40.0
SCREEN_DISQUALIFIED_SCORE = 0.00
SCREEN_IN_THRESHOLD = 60.00

# ---------------------------------------------------------------------------
# Session scheduling (PRD 3.5)
# ---------------------------------------------------------------------------
SESSION_BUFFER_MINUTES = 30
MAX_RESCHEDULE_COUNT = 2

# ---------------------------------------------------------------------------
# Consent retention (PRD 3.6)
# ---------------------------------------------------------------------------
RETENTION_CAP_DAYS_BY_SCOPE = {
    "RECORDING": 180,
    "TRANSCRIPT": 365,
    "PII_QUOTE": 90,
}
ARTIFACT_TYPE_TO_REQUIRED_SCOPE = {
    "RECORDING": "RECORDING",
    "TRANSCRIPT": "TRANSCRIPT",
    "PII_NOTE": "PII_QUOTE",
}
PURGE_REASON_CONSENT_REVOKED = "CONSENT_REVOKED"
PURGE_REASON_RETENTION_EXPIRED = "RETENTION_EXPIRED"
INADMISSIBLE_REASON_ARTIFACT_PURGED = "ARTIFACT_PURGED"
RETRACTION_REASON_EVIDENCE_WITHDRAWN = "EVIDENCE_WITHDRAWN"

# ---------------------------------------------------------------------------
# Evidence strength (PRD 3.7)
# ---------------------------------------------------------------------------
WEIGHT_CLASS_WEIGHTS = {
    "DIRECT_QUOTE": 1.00,
    "OBSERVED_BEHAVIOR": 0.85,
    "SELF_REPORT": 0.50,
}
METHOD_MULTIPLIERS = {
    "USABILITY_TEST": 1.20,
    "DIARY_STUDY": 1.10,
    "INTERVIEW": 1.00,
    "SURVEY": 0.70,
}
SEVERITY_MULTIPLIERS = {
    "HIGH": 1.50,
    "MEDIUM": 1.00,
    "LOW": 0.60,
}
PROVISIONAL_DIVISOR = 4.00
CORROBORATED_DIVISOR = 3.00
CORROBORATION_PARTICIPANT_TARGET = 5
EVIDENCE_STRENGTH_CEILING = 1.00

FINDING_LOCK_MIN_DISTINCT_PARTICIPANTS = 3
FINDING_PUBLISH_MIN_STRENGTH = 0.45
FINDING_RETRACTION_STRENGTH_FLOOR = 0.45
FINDING_RETRACTION_PARTICIPANT_FLOOR = 3

# ---------------------------------------------------------------------------
# Themes (PRD 3.7)
# ---------------------------------------------------------------------------
THEME_MAX_DEPTH = 3
THEME_ESTABLISHED_WEIGHT = 1.20

# ---------------------------------------------------------------------------
# Settlement (PRD 3.9)
# ---------------------------------------------------------------------------
SCREEN_OUT_STIPEND_CENTS = 200

# ---------------------------------------------------------------------------
# Metrics / impact score (PRD 3.9)
# ---------------------------------------------------------------------------
IMPACT_ACCEPTANCE_POINTS = 40.0
IMPACT_FINDINGS_TARGET = 3
IMPACT_FINDINGS_POINTS = 30.0
IMPACT_RECRUITMENT_POINTS = 20.0
IMPACT_FOLLOW_UP_POINTS = 10.0

# ---------------------------------------------------------------------------
# Field length limits (PRD 3.1, 3.7, 3.8)
# ---------------------------------------------------------------------------
MAX_DECISION_TITLE_LENGTH = 200
MAX_QUESTION_LENGTH = 500
MAX_STATEMENT_LENGTH = 500
MAX_RECOMMENDATION_LENGTH = 1000
MAX_FOLLOW_UP_DESCRIPTION_LENGTH = 500
