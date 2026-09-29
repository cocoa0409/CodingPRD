"""
Domain constants for the Player Tracking Data Ops API.

Every literal here is transcribed from the PRD so that test bodies never
hard-code a magic number whose provenance a reader cannot check.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.6)
# ---------------------------------------------------------------------------

# "Before any client sets it, the logical clock reads exactly 2026-08-01T00:00:00Z"
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# The instant most scenarios pin the clock to before doing any domain work.
CLOCK_NOON = "2026-08-01T12:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------

ROLE_LEAGUE_DATA_OPS = "LeagueDataOps"
ROLE_CALIBRATION_ENGINEER = "CalibrationEngineer"
ROLE_STATISTICIAN = "Statistician"
ROLE_QUALITY_REVIEWER = "QualityReviewer"
ROLE_CLUB_DATA_OFFICER = "ClubDataOfficer"
ROLE_LICENSEE = "Licensee"

ALL_ROLES = [
    ROLE_LEAGUE_DATA_OPS,
    ROLE_CALIBRATION_ENGINEER,
    ROLE_STATISTICIAN,
    ROLE_QUALITY_REVIEWER,
    ROLE_CLUB_DATA_OFFICER,
    ROLE_LICENSEE,
]

# ---------------------------------------------------------------------------
# Venue / installation (PRD 3.1, 3.2)
# ---------------------------------------------------------------------------

TRACKING_TECHS = ["OPTICAL", "SENSOR_UWB", "HYBRID"]
MODALITIES = ["OPTICAL_CAMERA", "UWB_ANCHOR", "LIDAR"]

POSTURE_UNCERTIFIED = "UNCERTIFIED"
POSTURE_CERTIFIED = "CERTIFIED"
POSTURE_RESTRICTED = "RESTRICTED"

INSTALLATION_DEPLOYED = "DEPLOYED"
INSTALLATION_CALIBRATING = "CALIBRATING"
INSTALLATION_VALIDATED = "VALIDATED"
INSTALLATION_CERTIFIED = "CERTIFIED"
INSTALLATION_RECALIBRATION_REQUIRED = "RECALIBRATION_REQUIRED"
INSTALLATION_RETIRED = "RETIRED"

# Calibration verdict thresholds (PRD 3.2)
CALIBRATION_PASS_CEILING_MM = 90.00
CALIBRATION_PROVISIONAL_CEILING_MM = 140.00
CALIBRATION_MIN_SAMPLE_COUNT = 5000
CALIBRATION_MIN_REFERENCE_POINT_COUNT = 12

RESULT_PASS = "PASS"
RESULT_PROVISIONAL = "PROVISIONAL"
RESULT_FAIL = "FAIL"
RESULT_INVALID = "INVALID"

# "the elapsed time from latest_run_recorded_at_utc to the current logical clock
#  must be at most 72 hours"
CERTIFICATION_VALIDITY_HOURS = 72

# ---------------------------------------------------------------------------
# Consent (PRD 3.3)
# ---------------------------------------------------------------------------

CURRENT_CBA_VERSION = "CBA-2026A"

SCOPE_BIOMETRIC_TRACKING = "BIOMETRIC_TRACKING"
SCOPE_POSITIONAL_ONLY = "POSITIONAL_ONLY"

CONSENT_PENDING = "PENDING"
CONSENT_ACTIVE = "ACTIVE"
CONSENT_WITHDRAWN = "WITHDRAWN"
CONSENT_EXPIRED = "EXPIRED"

RELEASE_NONE = "NONE"
RELEASE_GRANTED = "GRANTED"
RELEASE_WITHDRAWN = "WITHDRAWN"
RELEASE_EXPIRED = "EXPIRED"

# ---------------------------------------------------------------------------
# Games (PRD 3.4)
# ---------------------------------------------------------------------------

COLLECTION_SCHEDULED = "SCHEDULED"
COLLECTION_LIVE = "LIVE"
COLLECTION_SUSPENDED = "SUSPENDED_COLLECTION"
COLLECTION_COLLECTED = "COLLECTED"
COLLECTION_ARCHIVED = "ARCHIVED"

CERTIFICATION_PENDING = "PENDING"
CERTIFICATION_PROVISIONAL = "PROVISIONAL"
CERTIFICATION_OFFICIAL = "OFFICIAL"
CERTIFICATION_DISPUTED = "DISPUTED"

QUALITY_FLAG_CLEAN = "CLEAN"
QUALITY_FLAG_DEGRADED = "DEGRADED"

TRACKING_GENERATIONS = ["G1", "G2", "G3"]

# ---------------------------------------------------------------------------
# Event tags and corrections (PRD 3.5, 3.6)
# ---------------------------------------------------------------------------

TAG_TYPES = ["SHOT", "PASS", "FOUL", "SUBSTITUTION"]

TAG_DRAFT = "DRAFT"
TAG_SUBMITTED = "SUBMITTED"
TAG_ACCEPTED = "ACCEPTED"
TAG_UNDER_CORRECTION = "UNDER_CORRECTION"
TAG_SUPERSEDED = "SUPERSEDED"

REASON_WRONG_PLAYER = "WRONG_PLAYER"
REASON_WRONG_CLOCK = "WRONG_CLOCK"
REASON_WRONG_TYPE = "WRONG_TYPE"
REASON_BIOMETRIC_REMOVAL = "BIOMETRIC_REMOVAL"

CORRECTION_SUBMITTED = "SUBMITTED"
CORRECTION_APPROVED = "APPROVED"
CORRECTION_REJECTED = "REJECTED"

# Quality index (PRD 3.6)
QUALITY_INDEX_FLOOR = 0.8000
QUALITY_WEIGHT_CONFIDENCE = 0.5
QUALITY_WEIGHT_PENALTY = 0.3
QUALITY_WEIGHT_COMPLETENESS = 0.2
PENALTY_WEIGHT_APPROVED = 1.0
PENALTY_WEIGHT_REJECTED = 0.25
EXPECTED_ACCEPTED_TAGS_PER_GAME = 4

# ---------------------------------------------------------------------------
# Rights windows (PRD 3.7)
# ---------------------------------------------------------------------------

RIGHTS_CLASS_BROADCAST_LIVE = "BROADCAST_LIVE"
RIGHTS_CLASS_IN_VENUE_DISPLAY = "IN_VENUE_DISPLAY"
RIGHTS_CLASS_COMMERCIAL_LICENSE = "COMMERCIAL_LICENSE"
RIGHTS_CLASS_LEAGUE_ARCHIVE = "LEAGUE_ARCHIVE"

HOLDER_LEAGUE = "LEAGUE"
HOLDER_CLUB = "CLUB"
HOLDER_LICENSEE = "LICENSEE"

WINDOW_ACTIVE = "ACTIVE"
WINDOW_REVOKED = "REVOKED"

TERRITORY_GLOBAL = "GLOBAL"

# "league_reserve_minutes is fifteen percent of the game's licensable_minutes,
#  rounded up to a whole minute"
LEAGUE_RESERVE_FRACTION = 0.15

# "both the candidate interval and each existing interval are first expanded by
#  300 seconds, five minutes, on each side"
BROADCAST_LIVE_BUFFER_SECONDS = 300

# ---------------------------------------------------------------------------
# Licensees and feed sessions (PRD 3.8)
# ---------------------------------------------------------------------------

LICENSEE_CLASSES = ["BROADCASTER", "COMMERCIAL_LICENSEE", "DEVELOPER"]

TIER_BRONZE = "BRONZE"
TIER_SILVER = "SILVER"
TIER_GOLD = "GOLD"

TIER_RATE_CENTS = {
    TIER_BRONZE: 40,
    TIER_SILVER: 30,
    TIER_GOLD: 22,
}

TIER_SCOPES = {
    TIER_BRONZE: ["POSITIONAL"],
    TIER_SILVER: ["POSITIONAL", "EVENT"],
    TIER_GOLD: ["POSITIONAL", "EVENT", "BIOMETRIC"],
}

SCOPE_POSITIONAL = "POSITIONAL"
SCOPE_EVENT = "EVENT"
SCOPE_BIOMETRIC = "BIOMETRIC"

DELIVERY_REALTIME = "REALTIME"
DELIVERY_POST_GAME = "POST_GAME"

SESSION_ACTIVE = "ACTIVE"
SESSION_SUSPENDED = "SUSPENDED"
SESSION_TERMINATED = "TERMINATED"

HALT_VENUE_DEGRADED = "VENUE_DEGRADED"
HALT_CONSENT_WITHDRAWN = "CONSENT_WITHDRAWN"
HALT_CONSENT_EXPIRED = "CONSENT_EXPIRED"
HALT_CLIENT_REQUEST = "CLIENT_REQUEST"
HALT_SLA_BREACH_THRESHOLD = "SLA_BREACH_THRESHOLD"

# Latency premium tiers (PRD 3.8)
LATENCY_PREMIUM_MS = 250
LATENCY_STANDARD_MS = 1000
MULTIPLIER_PREMIUM = 1.50
MULTIPLIER_STANDARD = 1.20
MULTIPLIER_BASE = 1.00

# "a quarter of the record's charge ... is added to the licensee's sla_credit_cents"
SLA_CREDIT_FRACTION = 0.25

# "on the third breach recorded against a single session, that session moves
#  ACTIVE -> SUSPENDED"
SLA_BREACH_SUSPEND_THRESHOLD = 3

# ---------------------------------------------------------------------------
# Normalization (PRD 3.9)
# ---------------------------------------------------------------------------

BASIS_RAW_GENERATION = "RAW_GENERATION"
BASIS_CANONICAL_SEASON = "CANONICAL_SEASON"

METRIC_TOTAL_DISTANCE = "TOTAL_DISTANCE_M"
METRIC_SPRINT_DISTANCE = "SPRINT_DISTANCE_M"

GENERATION_SCALE = {
    "G1": 1.042,
    "G2": 1.017,
    "G3": 1.000,
}

CANONICAL_DRIFT_PCT = {
    "G1": -0.6,
    "G2": -0.2,
    "G3": 0.0,
}

MAPPING_VERSION = "MAP-2026.1"

# ---------------------------------------------------------------------------
# Shared numeric tolerances
# ---------------------------------------------------------------------------

# quality_index and normalized_value are stored rounded, so comparisons are
# made with a tolerance well below the last stored digit.
FOUR_DP_TOLERANCE = 1e-9
TWO_DP_TOLERANCE = 1e-9
