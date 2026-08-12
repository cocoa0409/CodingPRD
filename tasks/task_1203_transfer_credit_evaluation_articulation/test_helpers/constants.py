"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# Logical clock fixed default (PRD: the logical clock reads exactly this
# before any client sets it).
DEFAULT_LOGICAL_CLOCK = "2026-05-01T00:00:00Z"

# Grade scale (letter -> grade points), one-decimal literals.
GRADE_SCALE = {
    "A": 4.0,
    "A-": 3.7,
    "B+": 3.3,
    "B": 3.0,
    "B-": 2.7,
    "C+": 2.3,
    "C": 2.0,
    "C-": 1.7,
    "D": 1.0,
    "F": 0.0,
}

# Transferability threshold (inclusive).
TRANSFER_MIN_GRADE_POINTS = 2.0

# Credit conversion factors.
PROVISIONAL_QUARTER_FACTOR = 0.75
PROVISIONAL_SEMESTER_FACTOR = 1.0
EXACT_QUARTER_FACTOR = 2.0 / 3.0
EXACT_SEMESTER_FACTOR = 1.0

# Credit-cap waterfall slot needs and global cap.
MAX_TRANSFER_CREDITS = 60.0
SLOT_NEED_MAJOR_CORE = 30.0
SLOT_NEED_MAJOR_ELECTIVE = 12.0
SLOT_NEED_GENED_COMMS = 6.0
SLOT_NEED_GENED_MATH = 6.0
SLOT_NEED_GENED_SCIENCE = 6.0
SLOT_NEED_GENED_HUMANITIES = 6.0
SLOT_NEED_GENED_SOCIAL = 6.0
SLOT_NEED_FREE_ELECTIVE = 24.0
RESIDENCY_MIN_INSTITUTIONAL_CREDITS = 30.0

# Prior-learning lifetime cap.
MAX_PLA_CREDITS = 30.0

# Appeal timeliness window (days after petition decision, inclusive).
APPEAL_WINDOW_DAYS = 30

THRESHOLDS = {
    "TRANSFER_MIN_GRADE_POINTS": TRANSFER_MIN_GRADE_POINTS,
    "MAX_TRANSFER_CREDITS": MAX_TRANSFER_CREDITS,
    "MAX_PLA_CREDITS": MAX_PLA_CREDITS,
    "RESIDENCY_MIN_INSTITUTIONAL_CREDITS": RESIDENCY_MIN_INSTITUTIONAL_CREDITS,
    "APPEAL_WINDOW_DAYS": APPEAL_WINDOW_DAYS,
}
