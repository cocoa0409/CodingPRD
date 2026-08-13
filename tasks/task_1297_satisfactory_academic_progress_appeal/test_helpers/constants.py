"""Domain thresholds and shared constants from the PRD."""

# Federal-practice policy defaults carried by a program when the caller omits
# the optional policy knobs (PRD section 3.1).
DEFAULT_MIN_GPA = 2.0
DEFAULT_MIN_PACE_PCT = 67.0
DEFAULT_APPEAL_WINDOW_DAYS = 14
DEFAULT_REMINDER_OFFSET_DAYS = [7, 13]

# Maximum-timeframe multiplier: the cap is floor(required_credits * 1.5)
# (PRD section 3.3).
MAX_TF_MULTIPLIER = 1.5

# The logical clock at server startup (PRD section 2.7). The server never
# reads the wall clock.
CLOCK_START = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    "MIN_GPA": DEFAULT_MIN_GPA,
    "MIN_PACE_PCT": DEFAULT_MIN_PACE_PCT,
    "APPEAL_WINDOW_DAYS": DEFAULT_APPEAL_WINDOW_DAYS,
    "REMINDER_OFFSET_DAYS": DEFAULT_REMINDER_OFFSET_DAYS,
    "MAX_TF_MULTIPLIER": MAX_TF_MULTIPLIER,
}

# Standard academic calendar used by fixtures: five non-overlapping terms
# with monotonically increasing ordinals (seq drives plan coverage math).
STANDARD_TERMS = [
    {"seq": 1, "start_date": "2026-01-12", "end_date": "2026-05-08"},
    {"seq": 2, "start_date": "2026-05-18", "end_date": "2026-08-14"},
    {"seq": 3, "start_date": "2026-08-24", "end_date": "2026-12-11"},
    {"seq": 4, "start_date": "2027-01-11", "end_date": "2027-05-07"},
    {"seq": 5, "start_date": "2027-05-17", "end_date": "2027-08-13"},
]

# The canonical "failing term" grade line: attempted 6, earned 3, GPA 1.0,
# pace 50.00. Two of these in a row walk a student GOOD_STANDING -> WARNING
# -> SUSPENSION under default policy thresholds.
FAILING_HALF_TERM = {"attempted_credits": 6, "earned_credits": 3,
                     "quality_points": 6.0, "gpa_hours": 6}
