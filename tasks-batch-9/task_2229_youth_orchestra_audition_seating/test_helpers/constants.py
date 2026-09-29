"""Literal values the PRD pins down, plus deterministic fixture defaults."""

# --------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# --------------------------------------------------------------------------

# "Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z"
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Canonical fixture "now": inside the season year, before every audition window
# used by the helpers below.
FIXTURE_CLOCK = "2026-08-05T09:00:00Z"


# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


# --------------------------------------------------------------------------
# Rubric weights and composites (PRD §3.4)
# --------------------------------------------------------------------------

TONE_WEIGHT = 1.2
RHYTHM_WEIGHT = 1.0
INTONATION_WEIGHT = 1.0
SIGHT_READING_WEIGHT = 0.8

MIN_RUBRIC_SCORE = 0
MAX_RUBRIC_SCORE = 25

# "When the round holds four or more sheets, exactly one sheet holding the
# maximum weighted_total and exactly one sheet holding the minimum are
# discarded"
TRIM_MIN_SHEET_COUNT = 4

DEFAULT_QUORUM_REQUIRED = 3
MIN_QUORUM_REQUIRED = 2
MAX_QUORUM_REQUIRED = 5

MIN_PANELIST_IDS = 2
MAX_PANELIST_IDS = 5

DEFAULT_SLOT_CAPACITY = 1
MIN_SLOT_CAPACITY = 1
MAX_SLOT_CAPACITY = 8

MIN_EXCERPT_IDS = 1
MAX_EXCERPT_IDS = 6

# "requires revision_round to be strictly below two"
MAX_REVISION_ROUND = 2


# --------------------------------------------------------------------------
# Tier bands (PRD §3.4)
# --------------------------------------------------------------------------

SYMPHONY_THRESHOLD = 85.00
PHILHARMONIC_THRESHOLD = 75.00
CONCERT_ORCHESTRA_THRESHOLD = 62.50


# --------------------------------------------------------------------------
# Room and panel occupancy buffer (PRD §3.3)
# --------------------------------------------------------------------------

ROOM_TURNOVER_BUFFER_MINUTES = 15


# --------------------------------------------------------------------------
# Tuition (PRD §3.7)
# --------------------------------------------------------------------------

TIER_MULTIPLIER = {
    "SYMPHONY": 1.25,
    "PHILHARMONIC": 1.00,
    "CONCERT_ORCHESTRA": 0.80,
}

SIBLING_DISCOUNT_PCT = 0.10
LOYALTY_CREDIT_PCT_PER_YEAR = 0.015
LOYALTY_MAX_CREDITED_YEARS = 4

INSTRUMENT_LOAN_FEE_CENTS = {
    "STRING": 4500,
    "WIND": 6500,
    "PERCUSSION": 9000,
}


# --------------------------------------------------------------------------
# Financial aid (PRD §3.7)
# --------------------------------------------------------------------------

AID_CAP_PCT = {
    "BAND_A": 0.60,
    "BAND_B": 0.40,
    "BAND_C": 0.25,
}

AID_BAND_POINTS = {
    "BAND_A": 40,
    "BAND_B": 25,
    "BAND_C": 10,
}

AID_TIER_POINTS = {
    "SYMPHONY": 5,
    "PHILHARMONIC": 3,
    "CONCERT_ORCHESTRA": 1,
}

AID_SIBLING_POINTS = 8
AID_LOAN_POINTS = 6
AID_SENIORITY_POINTS_PER_YEAR = 3
AID_SENIORITY_MAX_YEARS = 5

PER_MEMBER_AID_CEILING_PCT = 0.30
MIN_AWARD_CENTS = 5000


# --------------------------------------------------------------------------
# Offers and excuses (PRD §3.5, §3.8)
# --------------------------------------------------------------------------

WAITLIST_PROMOTION_TTL_HOURS = 72
EXCUSE_WINDOW_HOURS = 48


# --------------------------------------------------------------------------
# Attendance and eligibility (PRD §3.8)
# --------------------------------------------------------------------------

ATTENDANCE_WEIGHTS = {
    "PRESENT": 1.0,
    "EXCUSED_ABSENT": 0.75,
    "TARDY": 0.5,
    "ABSENCE_UNVERIFIED": 0.0,
    "EXCUSE_PENDING": 0.0,
    "UNEXCUSED_ABSENT": 0.0,
}

ATTENDANCE_INDEX_THRESHOLD = 80.00
TARDY_TO_EFFECTIVE_ABSENCE_RATIO = 3
PROBATION_THRESHOLD = 3


# --------------------------------------------------------------------------
# Programming (PRD §3.9)
# --------------------------------------------------------------------------

GUEST_ARTIST_FEE_CAP_CENTS = 500000


# --------------------------------------------------------------------------
# Instrument classification (PRD §3.2)
# --------------------------------------------------------------------------

STRING_INSTRUMENTS = ["VIOLIN", "VIOLA", "CELLO", "BASS"]
PERCUSSION_INSTRUMENTS = ["PERCUSSION"]
WIND_INSTRUMENTS = [
    "FLUTE",
    "OBOE",
    "CLARINET",
    "BASSOON",
    "HORN",
    "TRUMPET",
    "TROMBONE",
]

INSTRUMENT_CLASS_OF = {
    **{i: "STRING" for i in STRING_INSTRUMENTS},
    **{i: "PERCUSSION" for i in PERCUSSION_INSTRUMENTS},
    **{i: "WIND" for i in WIND_INSTRUMENTS},
}


# --------------------------------------------------------------------------
# Deterministic fixture values used by factories/fixtures
# --------------------------------------------------------------------------

SEASON_AUDITION_WINDOW_START = "2026-08-10T09:00:00Z"
SEASON_AUDITION_WINDOW_END = "2026-08-20T18:00:00Z"
SEASON_TUITION_BASE_CENTS = 123223
SEASON_TUITION_DUE_AT = "2026-12-01T00:00:00Z"
SEASON_AID_BUDGET_CENTS = 100000

SLOT_START_AT = "2026-08-12T10:00:00Z"
SLOT_END_AT = "2026-08-12T10:30:00Z"

OFFER_EXPIRES_AT = "2026-09-01T00:00:00Z"
