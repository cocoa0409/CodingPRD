"""Domain thresholds — numeric constants named by the PRD workflows.

Attendance determination (PRD attendance section): a full day is at least
240 synchronous minutes with at least 2 engagement check-ins; a half day is
at least 120 minutes. Truancy (PRD truancy paragraphs): the window covers the
10 most recent attendance records and the flag threshold is 3 unexcused days.
Device returns (PRD stipend section): hardware is due back 30 days after
withdrawal.
"""

# Attendance determination thresholds (inclusive)
FULL_DAY_MINUTES = 240
HALF_DAY_MINUTES = 120
MIN_CHECKINS = 2

# Truancy window and threshold
TRUANCY_WINDOW_SCHOOL_DAYS = 10
TRUANCY_THRESHOLD = 3

# Device return pipeline
DEVICE_RETURN_WINDOW_DAYS = 30

# Common clock positions used across setups. The server's logical clock starts
# at exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time.
CLOCK_START = "2026-08-01T00:00:00Z"
DEFAULT_ENROLL_CLOCK = "2026-08-03T08:00:00Z"
DEFAULT_TERM_START_DATE = "2026-08-03"

TEST_DEFAULTS = {
    "FUNDING_RATE_CENTS": 500,
    "ENROLLMENT_CAP": 50,
    "GRADE_LEVEL": 6,
    "DATE_OF_BIRTH": "2012-01-01T00:00:00Z",
    "STIPEND_AMOUNT_CENTS": 50000,
    "CASELOAD_CAP": 30,
    "SEAT_CAPACITY": 5,
    "SERVICE_DURATION_MINUTES": 30,
}
