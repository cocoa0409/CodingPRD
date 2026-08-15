"""Domain thresholds — numeric constants named by PRD Sections 2-3."""

# Logical clock startup default (PRD §2.4).
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Screening fit score (PRD §3.2).
FIT_AGE_POINTS = 40
FIT_REGION_POINTS = 30
FIT_PLATFORM_POINTS = 30
FIT_PASS_THRESHOLD = 60

# NDA signature lifetime (PRD §3.3): creation instant plus seven days.
SIGNATURE_TTL_DAYS = 7

# Access keys (PRD §3.4).
DEFAULT_KEY_TTL_HOURS = 72
KEY_CODE_PREFIX = "KEY-"
KEY_CODE_ALNUM_LEN = 12

# Sessions (PRD §3.5): standard test session windows on 2026-08-10.
SESSION_DAY = "2026-08-10"
MODERATOR_BUFFER_MINUTES = 15

# No-show discipline (PRD §3.5).
STRIKE_LIMIT = 3
STRIKE_WINDOW_DAYS = 90

# Incentive amounts (PRD §3.8), integer cents.
BASE_PER_SESSION_CENTS = 5000
SURVEY_BONUS_CENTS = 1000
NO_SHOW_PENALTY_CENTS = 2000
TIER_TOP_MIN_ATTENDED = 3       # >= 3 -> 1.5x
TIER_MID_ATTENDED = 2           # == 2 -> 1.25x
TIER_TOP_MULTIPLIER = 1.5
TIER_MID_MULTIPLIER = 1.25
TIER_BASE_MULTIPLIER = 1.0

# Feedback priority (PRD §3.7).
SEVERITY_WEIGHTS = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 5}
REACH_CAP = 1000
REACH_FACTOR = 0.5
P1_MIN = 400
P2_MIN = 200
P3_MIN = 80
FORCE_P1_REACH = 100

# Breach risk weights (PRD §3.9), risk_score capped at 100.
RISK_WEIGHTS = {"MINOR": 10, "MAJOR": 25, "CRITICAL": 40}
RISK_SCORE_CAP = 100

# Opaque operator identities used by payout / breach workflows.
OFFICER_1 = "officer-1"
OFFICER_2 = "officer-2"
OFFICER_3 = "officer-3"
LEGAL_1 = "legal-1"
RESEARCHER_1 = "researcher-1"
