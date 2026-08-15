"""Domain thresholds — numeric constants from PRD §2 and §3."""

# Logical clock (PRD §2.5)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Fundraising requirement (PRD §3.2)
BASE_REQUIREMENT_CENTS = {
    "MOBILITY": 1_500_000,
    "PTSD": 1_800_000,
    "AUTISM": 1_800_000,
    "FACILITY": 900_000,
}
BRACKET1_LIMIT_CENTS = 3_000_000
BRACKET2_LIMIT_CENTS = 6_000_000
BRACKET3_LIMIT_CENTS = 10_000_000
SUBSIDY_TIER_THRESHOLD_CENTS = 1_000_000
SUBSIDY_PCT_HIGH = 0.10
SUBSIDY_PCT_LOW = 0.15
CONTRIBUTION_MIN_CENTS = 100

# Waitlist rank score (PRD §3.2)
WAIT_PTS_PER_DAY = 0.5
WAIT_CAP = 40
URGENCY_PTS = {"STANDARD": 10, "HIGH": 25, "CRITICAL": 40}
HOME_PTS_PER_POINT = 2
HOME_CAP = 20
FUNDRAISING_BONUS = 15
DISSOLVE_PENALTY = 10

# Health clearance (PRD §3.5)
HIP_PTS = {"EXCELLENT": 30, "GOOD": 24, "FAIR": 12, "POOR": 0}
ELBOW_PTS = {"NORMAL": 20, "GRADE1": 8, "GRADE2": 0}
EYE_PTS = {"CLEAR": 15, "ABNORMAL": 0}
CARDIAC_PTS = {"NORMAL": 15, "ABNORMAL": 0}
GENETIC_PTS = {"CLEAR": 20, "CARRIER": 10, "AFFECTED": 0}
DONATED_THRESHOLD = 84
BRED_THRESHOLD = 92

# A canonical all-pass screening for a DONATED dog: 24+20+15+15+10 = 84 (PRD §3.5).
DONATED_PASS_SCREENING = {
    "hip_grade": "GOOD",
    "elbow_grade": "NORMAL",
    "eye_result": "CLEAR",
    "cardiac_result": "NORMAL",
    "genetic_panel": "CARRIER",
}
DONATED_PASS_SCORE = 84

# Training advancement gates (PRD §3.6)
GATE_MIN_MILESTONES = 6
GATE_CUMULATIVE = 80.0
GATE_ROLLING = 70.0
GATE_FLOOR_RECENT = 40
GATE_MAX_LOW_TOTAL = 1
CERTIFY_TASK_MIN_SCORE = 80

# A canonical six-milestone sequence that satisfies every advancement gate:
# TASK_WORK mean 89.67, PUBLIC_MANNERS 88, OBEDIENCE+SOCIALIZATION mean 83.5,
# cumulative 80.8, rolling window (82, 84, 85...) always >= 70, no score < 50.
ADVANCING_MILESTONES = [
    {"category": "TASK_WORK", "task_code": "RETRIEVE_ITEMS", "score": 95},
    {"category": "TASK_WORK", "task_code": "OPEN_DOORS", "score": 90},
    {"category": "PUBLIC_MANNERS", "score": 88},
    {"category": "OBEDIENCE", "score": 85},
    {"category": "SOCIALIZATION", "score": 82},
    {"category": "TASK_WORK", "task_code": "RETRIEVE_ITEMS", "score": 84},
]

# PAT scoring (PRD §3.7)
PAT_PASS_THRESHOLD = 80.0
PAT_EXERCISE_CODES = (
    ["C1", "C2", "C3", "C4", "C5", "C6"]
    + ["P1", "P2", "P3", "P4"]
    + ["S1", "S2"]
)
# Perfect 3s on all 12 exercises -> every section 100.0 -> official 100.0, all gates hold.
PAT_PERFECT_SCORES = [
    {"exercise_code": code, "raw_score": 3} for code in PAT_EXERCISE_CODES
]

# Graduation (PRD §3.7)
ATTENDANCE_THRESHOLD = 85.0

# Class shape (PRD §3.7)
CLASS_MIN_CAPACITY = 2
CLASS_MAX_CAPACITY = 6

# Schedules (PRD §3.8)
RECERT_INTERVAL_DAYS = 365
FOLLOWUP_OFFSETS_DAYS = [90, 180, 270]
FOLLOWUP_GRACE_DAYS = 7
FOLLOWUP_MIN_GAP_DAYS = 7
RECERT_WINDOW_DAYS = 30
SUPPORT_REOPEN_WINDOW_DAYS = 14

# Standard MOBILITY applicant with zero credit bracket: provisional requirement is
# 1,500,000 - 0 - 150,000 = 1,350,000 cents (PRD §3.2 provisional variant).
MOBILITY_ZERO_CREDIT_REQUIREMENT = 1_350_000
# FACILITY zero-credit: gross 900,000 < 1,000,000 -> 15% subsidy on gross:
# 900,000 - 0 - 135,000 = 765,000 (PRD §3.2 provisional variant).
FACILITY_ZERO_CREDIT_REQUIREMENT = 765_000
