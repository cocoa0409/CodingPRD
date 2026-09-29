"""Numeric thresholds, boundaries and pinned constants taken from the PRD."""

from __future__ import annotations

from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

#: The clock value every fresh service instance reports before any client sets it.
INITIAL_CLOCK = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Intake / functioning levels
# ---------------------------------------------------------------------------

MIN_EFL_LEVEL = 1
MAX_EFL_LEVEL = 6

MAX_FULL_NAME_LENGTH = 120

#: Inclusive scale-score floors per test form, level 1 through level 6.
#: A score sitting exactly on a floor belongs to the higher level.
EFL_BAND_FLOORS: Dict[str, List[int]] = {
    "CASAS_R_900": [0, 201, 211, 221, 236, 246],
    "CASAS_M_900": [0, 194, 203, 214, 227, 236],
    "BEST_PLUS": [0, 401, 418, 439, 473, 507],
}

MIN_TEST_EVENT_SCALE_SCORE = 0
MAX_TEST_EVENT_SCALE_SCORE = 999


def efl_level_for(test_form: str, scale_score: int) -> int:
    """Derive the functioning level for a scale score under one test form."""
    floors = EFL_BAND_FLOORS[test_form]
    level = 1
    for index, floor in enumerate(floors):
        if scale_score >= floor:
            level = index + 1
    return level


# ---------------------------------------------------------------------------
# Sections, enrollment and attendance
# ---------------------------------------------------------------------------

MIN_SEATS_TOTAL = 1
MAX_SEATS_TOTAL = 60
MAX_WEEKLY_HOURS = 40.0

MIN_ATTENDANCE_HOURS_EXCLUSIVE = 0.0
MAX_ATTENDANCE_HOURS = 8.0
ATTENDANCE_HOUR_INCREMENT = 0.25

#: Posted-hour floor that flips ``post_test_eligible`` and opens the post-test.
POST_TEST_HOUR_THRESHOLD = 40.00

#: Whole UTC days that must pass since the placement pre-test's test date.
POST_TEST_MIN_INTERVAL_DAYS = 30


# ---------------------------------------------------------------------------
# Centres, rooms and proctors
# ---------------------------------------------------------------------------

PROVISIONAL_ALLOWED_SUBTESTS = ["MATH", "RLA"]
PROVISIONAL_MAX_SESSIONS_PER_WEEK = 2
FULL_ALLOWED_SUBTESTS = ["MATH", "RLA", "SCIENCE", "SOCIAL_STUDIES"]
FULL_MAX_SESSIONS_PER_WEEK = 20
SUSPENDED_MAX_SESSIONS_PER_WEEK = 0

MIN_SEAT_CAPACITY = 1
MAX_SEAT_CAPACITY = 200
DEFAULT_TURNAROUND_BUFFER_MINUTES = 45
MIN_TURNAROUND_BUFFER_MINUTES = 0
MAX_TURNAROUND_BUFFER_MINUTES = 120

DEFAULT_DAILY_HOUR_CAP = 8.00
MAX_DAILY_HOUR_CAP = 12.00


# ---------------------------------------------------------------------------
# Exam sittings
# ---------------------------------------------------------------------------

MAX_SESSION_DURATION_HOURS = 6.0
DEFAULT_SUPPORTED_FORMATS = ["STANDARD", "EXTRA_TIME"]
#: Minutes before ``starts_at`` at which the seating window opens.
CHECK_IN_WINDOW_LEAD_MINUTES = 60


# ---------------------------------------------------------------------------
# Exam fee assessment
# ---------------------------------------------------------------------------

BASE_EXAM_FEE_CENTS: Dict[str, int] = {
    "RLA": 3400,
    "MATH": 3000,
    "SCIENCE": 3000,
    "SOCIAL_STUDIES": 3000,
}

RETAKE_MULTIPLIER = 1.25
MAX_RETAKE_EXPONENT = 2

ALTERNATE_FORMAT_SURCHARGE_CENTS = 1200
SURCHARGED_FORMATS = ["LARGE_PRINT", "BRAILLE", "AUDIO"]

#: ``(inclusive lower bound on total_instructional_hours, discount percent)``
ATTENDANCE_DISCOUNT_TIERS: List[Tuple[float, int]] = [
    (0.0, 0),
    (12.0, 25),
    (40.0, 50),
    (100.0, 75),
]

MIN_RESULT_SCALE_SCORE = 100
MAX_RESULT_SCALE_SCORE = 200
PASSING_SUBTEST_SCORE = 145


# ---------------------------------------------------------------------------
# Credentials and transcripts
# ---------------------------------------------------------------------------

MIN_COMPOSITE_SCORE = 580
CREDENTIAL_SUBTEST_ORDER = ["MATH", "RLA", "SCIENCE", "SOCIAL_STUDIES"]

TRANSCRIPT_COPY_FEE_CENTS = 1500
TRANSCRIPT_RUSH_SURCHARGE_CENTS = 2500
MIN_TRANSCRIPT_COPIES = 1
MAX_TRANSCRIPT_COPIES = 10

#: ``(inclusive lower bound on base_charge_cents, waiver percent)``
TRANSCRIPT_WAIVER_TIERS: List[Tuple[int, int]] = [
    (0, 0),
    (3000, 10),
    (6000, 20),
]

STATE_RECORDS_FEE_ZERO_CENTS = 0
STATE_RECORDS_FEE_LOW_CENTS = 200
STATE_RECORDS_FEE_HIGH_CENTS = 500
STATE_RECORDS_FEE_HIGH_THRESHOLD_CENTS = 3000


# ---------------------------------------------------------------------------
# Performance funding
# ---------------------------------------------------------------------------

MEASURE_WEIGHTS: Dict[str, float] = {
    "EFL_GAIN": 1.00,
    "CREDENTIAL_ATTAINMENT": 1.50,
    "EMPLOYMENT_Q2": 1.25,
    "POSTSECONDARY_ENROLLMENT": 1.40,
}

MIN_RATE_CENTS_PER_WEIGHT = 1
