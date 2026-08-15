"""Domain thresholds and canonical values (PRD §2.4, §2.6, §3).

The canonical cycle below mirrors the deadlines and fee constants used across
the PRD's worked examples; every factory defaults to it so tests can move the
logical clock against known instants.
"""

# --- Logical clock (PRD §2.4) ---
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --- Canonical ExamCycle deadlines / window (PRD §3.1) ---
REGISTRATION_DEADLINE_AT = "2026-11-01T12:00:00Z"
ORDER_DEADLINE_AT = "2026-11-15T12:00:00Z"
SCORE_RELEASE_AT = "2027-07-05T12:00:00Z"
EXAM_WINDOW_START_AT = "2027-05-03T00:00:00Z"
EXAM_WINDOW_END_AT = "2027-05-21T23:59:59Z"

# --- Canonical fee constants (integer cents, PRD §2.6) ---
LATE_FEE_CENTS = 4000
UNUSED_EXAM_PENALTY_CENTS = 1500
FEE_REDUCTION_CENTS = 3600
BUDGET_CAP_CENTS = 100_000_000
REBATE_RATE_BP = 900  # 9% in basis points (PRD §3.1)

# --- Canonical course (PRD §3.2) ---
EXAM_FEE_CENTS = 9800
CREDIT_THRESHOLD_AP = 3
CREDIT_THRESHOLD_IB = 4

# --- Teacher authorization validity (PRD §3.2) ---
AUTHORIZATION_VALIDITY_DAYS = 730

# --- Proctor travel buffer (PRD §3.5) ---
PROCTOR_BUFFER_MINUTES = 30

# --- Canonical session window (inside the exam window) ---
SESSION_START_AT = "2027-05-05T09:00:00Z"
SESSION_END_AT = "2027-05-05T11:00:00Z"
# Clock reading after the canonical session ends (attendance allowed).
AFTER_SESSION_END_AT = "2027-05-05T12:00:00Z"

# --- Grade range (PRD §3.3) ---
GRADE_LEVEL_MIN = 9
GRADE_LEVEL_MAX = 12

TEST_DEFAULTS = {
    "CYCLE_NAME": "CYCLE-2027",
    "SUBJECT_CODE": "AP_CALC_BC",
    "TEACHER_NAME": "T Instructor",
    "TEACHER_EMAIL": "inst@x.edu",
    "STUDENT_NAME": "Stu A",
    "ROOM_NAME": "GYM",
    "ROOM_CAPACITY": 5,
}
