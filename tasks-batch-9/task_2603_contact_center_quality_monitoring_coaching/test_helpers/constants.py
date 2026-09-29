"""Domain thresholds and pinned literals drawn from the PRD.

Every value below is quoted in the PRD prose; the names exist so the test
suite reads as the rule rather than as a bare number.
"""
from __future__ import annotations

# --- The logical clock (PRD 2.4) -----------------------------------------
# "The clock starts at the fixed instant `2026-08-01T00:00:00Z`"
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- Pagination (PRD 2.3) ------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# --- Form authoring (PRD 3.1) -------------------------------------------
BEHAVIOR_WEIGHT_TOTAL_REQUIRED = 100.00
DEFAULT_MIN_COMPLIANCE_ITEM_SCORE = 3
MIN_MIN_COMPLIANCE_ITEM_SCORE = 1
DEFAULT_MAX_POINTS = 5
ALLOWED_MAX_POINTS = (3, 4, 5)
INITIAL_GUIDANCE_VERSION = 1
NAME_MIN_LEN = 1
NAME_MAX_LEN = 120
VERSION_LABEL_MIN_LEN = 1
VERSION_LABEL_MAX_LEN = 20
BEHAVIOR_CODE_MIN_LEN = 2
BEHAVIOR_CODE_MAX_LEN = 24
WEIGHT_PCT_MIN_EXCLUSIVE = 0.00
WEIGHT_PCT_MAX = 100.00

# --- Evaluator registration (PRD 3.2) -----------------------------------
DEFAULT_MAX_OPEN_ASSIGNMENTS = 3
MIN_MAX_OPEN_ASSIGNMENTS = 1
MAX_MAX_OPEN_ASSIGNMENTS = 20

# --- Interaction inputs (PRD 3.2 / 2.11) --------------------------------
CSAT_MIN = 1
CSAT_MAX = 5
IMPUTED_CSAT = 3

# --- Analytics risk score (PRD 3.3) -------------------------------------
SILENCE_WEIGHT = 0.45
SENTIMENT_WEIGHT = 0.35
CATEGORY_POINTS = {
    "PROFANITY": 25,
    "NO_DISCLOSURE": 30,
    "ESCALATION_REQUEST": 15,
    "CONSENT_OBJECTION": 40,
}
DISCLOSURE_GAP_BONUS = 15
CHANNEL_MULTIPLIER = {"VOICE": 1.20, "CHAT": 1.00, "EMAIL": 0.80}
RISK_SCORE_CAP = 100.00
PRIORITY_P1_FLOOR = 70.00
PRIORITY_P2_FLOOR = 40.00
SILENCE_PCT_MIN = 0.00
SILENCE_PCT_MAX = 100.00
SENTIMENT_DELTA_MIN = -1.00
SENTIMENT_DELTA_MAX = 1.00

# --- Sampling plans (PRD 3.4) -------------------------------------------
PER_AGENT_TARGET_VOLUME_MIN = 1
PER_AGENT_TARGET_VOLUME_MAX = 50
SOURCE_MIX_TOTAL = 100
LIVE_SELECTION_STATUSES = ("SELECTED", "ASSIGNED", "EVALUATED")

# --- Scoring and compliance (PRD 3.5) -----------------------------------
HIGH_SCORE_FLOOR = 85.00
ROLLING_WINDOW_SIZE = 4

# --- Dispute path (PRD 3.6) ---------------------------------------------
DISPUTE_WINDOW_DAYS = 7
DISPUTE_MAX_ROUNDS = 2
RATIONALE_MIN_LEN = 10
RATIONALE_MAX_LEN = 1000

# --- Calibration bands (PRD 3.7) ----------------------------------------
ALIGNED_MAX_ABS_DEVIATION = 3.00
MINOR_VARIANCE_MAX_ABS_DEVIATION = 7.00
SUSPENSION_ABS_DEVIATION_FLOOR = 15.00
CLOSED_ALIGNED_MAX_VARIANCE = 7.00
MIN_SUBMISSIONS_FOR_NON_VOID_CLOSE = 2

# --- Coaching sizing (PRD 3.8) ------------------------------------------
TIER_T1_MAX_DEFICIT = 5.00
TIER_T2_MAX_DEFICIT = 12.00
TIER_SEVERITY_MULTIPLIER = {"T1": 1.0, "T2": 1.25, "T3": 1.5}
TIER_GAIN_PER_SESSION = {"T1": 2.5, "T2": 2.0, "T3": 1.5}
TIER_ALLOWANCE_DAYS = {"T1": 30, "T2": 45, "T3": 60}
MIN_REQUIRED_SESSIONS = 1
MAX_REQUIRED_SESSIONS = 8
TIER_BUMP = {"T1": "T2", "T2": "T3", "T3": "T3"}
ESCALATION_FINDINGS_FLOOR = 2

# --- Recognition (PRD 3.8) ----------------------------------------------
RECOGNITION_INDEX_FLOOR = 92.00
RECOGNITION_MIN_EVALUATION_HISTORY = 2
RECOGNITION_POINTS_MIN = 1
RECOGNITION_POINTS_MAX = 500
RECOGNITION_HISTORY_STATUSES = ("SUBMITTED", "FINALIZED", "REOPENED")

# --- Identifier that resolves to nothing --------------------------------
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"
