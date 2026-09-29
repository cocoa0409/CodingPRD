"""
Business constants for the Concussion Protocol & Return-to-Play Administration API.

Every value here is quoted from the PRD (thresholds, windows, weights, base
amounts, tier multipliers and band edges).  Tests import these names instead of
repeating magic numbers, so a PRD change has exactly one edit site.
"""

# ─── API mount ────────────────────────────────────────────────────────────────

API_PREFIX = "/concussion-program"
CLOCK_PATH = "/_clock/set_current_utc"

# The clock reads this instant until it has been set explicitly for the first time.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ─── Symptom / examination thresholds ────────────────────────────────────────

SYMPTOM_RECURRENCE_THRESHOLD = 4
MIN_LOCKER_ROOM_EXAM_MINUTES = 8
INC_EXAM_BLOCK_MINUTES = 30

# ─── Evaluation deadlines ────────────────────────────────────────────────────

MANDATORY_EVAL_DEADLINE_MINUTES = 15
DISCRETIONARY_EVAL_DEADLINE_MINUTES = 45

# ─── Baseline testing ────────────────────────────────────────────────────────

BASELINE_VALIDITY_DAYS = 365
NO_BASELINE_PENALTY_POINTS = 15

# ─── Case severity index ─────────────────────────────────────────────────────

SEVERITY_BASE_POINTS = 40
SEVERITY_SYMPTOM_POINTS_PER_UNIT = 3
SEVERITY_SYMPTOM_CAP = 30
SEVERITY_RECURRENCE_POINTS_PER_UNIT = 12
SEVERITY_RECURRENCE_CAP = 24
SEVERITY_BASELINE_MULTIPLIER = 1.5
SEVERITY_BASELINE_CAP = 15
SEVERITY_PRIOR_CASE_POINTS = 10
SEVERITY_HIGH_THRESHOLD = 70

# ─── Return-to-play timeline ─────────────────────────────────────────────────

BASE_RTP_HOURS = 168
SEVERITY_SURCHARGE_HOURS = 72
POST_STAGE5_REST_HOURS = 24
RECURRENCE_PENALTY_HOURS = 48

# Dwell each stage must accumulate before it may be evaluated.
STAGE_MIN_HOURS = {1: 24, 2: 24, 3: 24, 4: 48, 5: 48}
# Rest after the previous stage passed, before the next stage may start.
STAGE_REST_HOURS = {2: 24, 3: 24, 4: 24, 5: 48}

STAGE_NAMES = {
    1: "SYMPTOM_LIMITED_ACTIVITY",
    2: "AEROBIC_EXERCISE",
    3: "SPORT_SPECIFIC_DRILLS",
    4: "NON_CONTACT_TRAINING",
    5: "FULL_CONTACT_PRACTICE",
}

# ─── Consultant clearance ────────────────────────────────────────────────────

INC_CLEARANCE_VALIDITY_HOURS = 168

# ─── Monitoring ──────────────────────────────────────────────────────────────

PROLONGED_SYMPTOM_DAYS = 21
POST_CLEARANCE_QUESTIONABLE_HOURS = 72


def offseason_start_at(season_year: int) -> str:
    """The off-season boundary for a season: 15 February of the following year."""
    return f"{season_year + 1}-02-15T00:00:00Z"


# ─── Injury reporting ────────────────────────────────────────────────────────

REPORT_WINDOW_OPEN_HOURS_BEFORE_KICKOFF = 96
REPORT_WINDOW_LATE_MINUTES_BEFORE_KICKOFF = 90

# ─── Auditing, pricing and sanctions ─────────────────────────────────────────

MAX_AUDIT_RESPONSE_ROUNDS = 2
SEASON_FINE_CAP_CENTS = 150_000_000

VIOLATION_CODE_CANONICAL_ORDER = [
    "UNAUTHORIZED_SAME_GAME_RETURN",
    "MISSING_INC_CLEARANCE",
    "MISSED_MANDATORY_REMOVAL",
    "EVALUATION_DEADLINE_BREACH",
    "INCOMPLETE_LOCKER_ROOM_EXAM",
    "BASELINE_TEST_MISSING",
    "LATE_INJURY_REPORT",
]

VIOLATION_WEIGHT = {
    "UNAUTHORIZED_SAME_GAME_RETURN": 25,
    "MISSING_INC_CLEARANCE": 20,
    "MISSED_MANDATORY_REMOVAL": 18,
    "EVALUATION_DEADLINE_BREACH": 15,
    "INCOMPLETE_LOCKER_ROOM_EXAM": 12,
    "BASELINE_TEST_MISSING": 8,
    "LATE_INJURY_REPORT": 6,
}

VIOLATION_BASE_CENTS = {
    "UNAUTHORIZED_SAME_GAME_RETURN": 25_000_000,
    "MISSING_INC_CLEARANCE": 20_000_000,
    "MISSED_MANDATORY_REMOVAL": 15_000_000,
    "EVALUATION_DEADLINE_BREACH": 5_000_000,
    "INCOMPLETE_LOCKER_ROOM_EXAM": 7_500_000,
    "BASELINE_TEST_MISSING": 2_500_000,
    "LATE_INJURY_REPORT": 1_500_000,
}

ESCALATION_TIER_MULTIPLIER = {
    "TIER_0": 1.00,
    "TIER_1": 1.50,
    "TIER_2": 2.00,
    "TIER_3": 3.00,
}

# TIER_0: compliance_score >= 90; TIER_1: 75..89; TIER_2: 60..74; TIER_3: < 60
ESCALATION_TIER_BANDS = [
    ("TIER_0", 90, None),
    ("TIER_1", 75, 89),
    ("TIER_2", 60, 74),
    ("TIER_3", None, 59),
]

# ACTIVE: compliance_score >= 90; PROBATION: 70..89; SANCTIONED: < 70
CLUB_POSTURE_BANDS = [
    ("ACTIVE", 90, None),
    ("PROBATION", 70, 89),
    ("SANCTIONED", None, 69),
]

# ─── Enumerations ────────────────────────────────────────────────────────────

CLUB_STATUSES = ["ACTIVE", "PROBATION", "SANCTIONED"]
ESCALATION_TIERS = ["TIER_0", "TIER_1", "TIER_2", "TIER_3"]

CLINICIAN_AFFILIATIONS = [
    "CLUB_AFFILIATED",
    "UNAFFILIATED_OBSERVER",
    "INDEPENDENT_CONSULTANT",
]
CLINICIAN_STATUSES = ["ACTIVE", "SUSPENDED"]

PLAYER_POSITIONS = ["QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "K", "P"]
BASELINE_STATUSES = ["NONE", "VALID", "RETEST_REQUIRED"]
AVAILABILITY_STATUSES = ["AVAILABLE", "PROTOCOL_RESTRICTED"]
INJURY_DESIGNATIONS = ["NONE", "QUESTIONABLE", "DOUBTFUL", "OUT"]

GAME_STATUSES = ["SCHEDULED", "IN_PROGRESS", "FINAL"]

BASELINE_TEST_STATUSES = ["VALID", "SUPERSEDED", "INVALIDATED", "EXPIRED"]
RETEST_REQUIRED_REASONS = [
    "NONE",
    "NEW_DIAGNOSIS",
    "ADMIN_INVALIDATION",
    "SEASON_ROLLOVER",
]

TRIGGER_SOURCES = [
    "CLUB_MEDICAL_STAFF",
    "UNAFFILIATED_OBSERVER",
    "GAME_OFFICIAL",
    "VIDEO_SPOTTER",
    "COACH",
]
MANDATORY_REMOVAL_TRIGGERS = [
    "UNAFFILIATED_OBSERVER",
    "GAME_OFFICIAL",
    "VIDEO_SPOTTER",
]

NO_GO_SIGNS = [
    "LOSS_OF_CONSCIOUSNESS",
    "ATAXIA",
    "CONFUSION",
    "AMNESIA",
    "BLANK_STARE",
    "MOTOR_INCOORDINATION",
]

EVALUATION_STATUSES = [
    "INITIATED",
    "SCREENED",
    "LOCKER_ROOM_EXAM",
    "CLEARED_ON_FIELD",
    "DIAGNOSED",
    "NO_CONCUSSION_CLEARED",
    "HELD_OUT_INCONCLUSIVE",
    "PROTOCOL_BREACH",
]
DIAGNOSIS_OUTCOMES = ["PENDING", "CONCUSSION", "NO_CONCUSSION", "INCONCLUSIVE"]

CASE_STATUSES = [
    "MANDATORY_REMOVAL",
    "RTP_IN_PROGRESS",
    "PENDING_INC_CLEARANCE",
    "STAGE_FROZEN",
    "CLEARED_FOR_CONTACT",
]
MONITORING_STATUSES = [
    "ACTIVE_SYMPTOM_WATCH",
    "PROLONGED_SYMPTOM_WATCH",
    "OFFSEASON_MONITORING",
    "MONITORING_CLOSED",
]
ROSTER_EXEMPTION_STATUSES = ["NONE", "GRANTED", "RELEASED"]

RETURN_STEP_STATUSES = [
    "IN_PROGRESS",
    "PASSED",
    "FAILED_SYMPTOM_RECURRENCE",
    "REVOKED",
]
STEP_OUTCOMES = ["PASS", "SYMPTOM_RECURRENCE"]

CLEARANCE_STATUSES = [
    "PENDING",
    "APPROVED",
    "DENIED_MORE_REST",
    "DENIED_INSUFFICIENT_DOCUMENTATION",
    "SUPERSEDED",
    "EXPIRED",
]
CLEARANCE_DECISIONS = [
    "APPROVED",
    "DENIED_MORE_REST",
    "DENIED_INSUFFICIENT_DOCUMENTATION",
]

AUDIT_STATUSES = [
    "OPEN",
    "FINDINGS_ISSUED",
    "CLUB_RESPONDED",
    "CLOSED_UPHELD",
    "CLOSED_DISMISSED",
]
AUDIT_DISPOSITIONS = ["PENDING", "UPHELD", "DISMISSED"]

PRACTICE_PARTICIPATIONS = ["DNP", "LIMITED", "FULL"]
INJURY_REPORT_STATUSES = ["FILED", "LATE_FILED", "AMENDED"]

# ─── Pagination ──────────────────────────────────────────────────────────────

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0
