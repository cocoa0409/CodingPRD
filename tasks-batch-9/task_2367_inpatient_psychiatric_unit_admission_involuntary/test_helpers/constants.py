"""Numeric and temporal constants the PRD pins by name.

Nothing here is derived from an implementation; each value is transcribed from
the specification so tests can express an expectation arithmetically instead of
hard-coding a magic number in twenty places.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple

API_PREFIX = "/behavioral-health"

# ---------------------------------------------------------------------------
# Clock (PRD 2.4, 2.6)
# ---------------------------------------------------------------------------

#: The logical clock reads exactly this instant at process start (PRD 2.4).
STARTUP_CLOCK_UTC = "2026-08-01T00:00:00Z"

#: Millisecond precision: every timestamp carries exactly three fractional
#: digits (PRD 2.6).
TIMESTAMP_FRACTIONAL_DIGITS = 3

# ---------------------------------------------------------------------------
# Court calendar (PRD 2.6)
# ---------------------------------------------------------------------------

#: Dates excluded from both the court and business calendars (PRD 2.6).
HOLIDAY_DATES: Tuple[str, ...] = (
    "2026-01-01",
    "2026-07-03",
    "2026-09-07",
    "2026-11-26",
    "2026-12-25",
)

COURT_DAY_OPEN_HOUR = 9
COURT_DAY_CLOSE_HOUR = 16
#: A judicial-day roll always lands on this wall time (PRD 2.6).
COURT_DAY_OPEN_TIME = "09:00:00.000Z"

BUSINESS_DAY_OPEN_HOUR = 8
BUSINESS_DAY_CLOSE_HOUR = 17
#: A business-day roll always lands on this wall time (PRD 2.6).
BUSINESS_DAY_OPEN_TIME = "08:00:00.000Z"
#: Nine business hours are available on each business day (PRD 2.6).
BUSINESS_HOURS_PER_DAY = 9

# ---------------------------------------------------------------------------
# Holds (PRD 3.3)
# ---------------------------------------------------------------------------

STATUTORY_HOURS_EMERGENCY_72H = 72
STATUTORY_HOURS_EXTENSION_14D = 336
#: A hold must be certified within four hours of its anchor (PRD 3.3).
CERTIFICATION_WINDOW_HOURS = 4

#: ``closure_reason`` values the specification pins verbatim (PRD 3.3, 3.4).
CLOSURE_REASON_STATUTORY_EXPIRY = "STATUTORY_EXPIRY"
CLOSURE_REASON_COURT_DENIED_EXTENSION = "COURT_DENIED_EXTENSION"

# ---------------------------------------------------------------------------
# Evaluations (PRD 3.2)
# ---------------------------------------------------------------------------

ACUITY_WEIGHT_DANGER_TO_SELF = 4
ACUITY_WEIGHT_DANGER_TO_OTHERS = 5
ACUITY_WEIGHT_GRAVE_DISABILITY = 3
ACUITY_WEIGHT_PRIOR_ADMISSION = 2
#: The prior-admission term is capped at three admissions (PRD 3.2).
ACUITY_PRIOR_ADMISSION_CAP = 3
ACUITY_WEIGHT_CAPACITY_ABSENT = 3

ACUITY_TIER_HIGH_MIN = 12
ACUITY_TIER_MODERATE_MIN = 7

#: The recency window for ``prior_admission_count_30d`` (PRD 3.2).
PRIOR_ADMISSION_WINDOW_DAYS = 30


def acuity_score(
    danger_to_self: bool,
    danger_to_others: bool,
    grave_disability: bool,
    prior_admission_count_30d: int,
    capacity_present: bool,
) -> int:
    """Reproduce the weighted acuity sum of PRD 3.2."""
    return (
        ACUITY_WEIGHT_DANGER_TO_SELF * int(danger_to_self)
        + ACUITY_WEIGHT_DANGER_TO_OTHERS * int(danger_to_others)
        + ACUITY_WEIGHT_GRAVE_DISABILITY * int(grave_disability)
        + ACUITY_WEIGHT_PRIOR_ADMISSION
        * min(ACUITY_PRIOR_ADMISSION_CAP, prior_admission_count_30d)
        + ACUITY_WEIGHT_CAPACITY_ABSENT * int(not capacity_present)
    )


def acuity_tier(score: int) -> str:
    """Map an acuity score onto its tier band (PRD 3.2)."""
    if score >= ACUITY_TIER_HIGH_MIN:
        return "HIGH"
    if score >= ACUITY_TIER_MODERATE_MIN:
        return "MODERATE"
    return "LOW"


# ---------------------------------------------------------------------------
# Units, beds and posture (PRD 3.1)
# ---------------------------------------------------------------------------

#: Only the two placement bed types count toward availability (PRD 3.1).
PLACEMENT_BED_TYPES: Tuple[str, ...] = (
    "STANDARD",
    "LIGATURE_RESISTANT_OBSERVATION",
)

#: The divisor in the restricted-posture threshold (PRD 3.1).
POSTURE_THRESHOLD_DIVISOR = 5
#: A RESTRICTED unit holds this many beds in reserve (PRD 3.1).
RESTRICTED_RESERVE_BEDS = 1

#: Ranking weight per acuity tier when the promotion queue is ordered (PRD 3.5).
ACUITY_RANK: Dict[str, int] = {"HIGH": 3, "MODERATE": 2, "LOW": 1}

#: The bed type that is an exact fit for each acuity tier (PRD 3.5).
EXACT_FIT_BED_TYPE: Dict[str, str] = {
    "HIGH": "LIGATURE_RESISTANT_OBSERVATION",
    "MODERATE": "LIGATURE_RESISTANT_OBSERVATION",
    "LOW": "STANDARD",
}


def posture_threshold(licensed_placement_bed_count: int) -> int:
    """The restricted threshold of PRD 3.1: ``max(1, floor(licensed / 5))``."""
    return max(1, licensed_placement_bed_count // POSTURE_THRESHOLD_DIVISOR)


def expected_posture(
    licensed_placement_bed_count: int, raw_available_bed_count: int
) -> str:
    """Reproduce the posture ladder of PRD 3.1."""
    if raw_available_bed_count == 0:
        return "CLOSED"
    if raw_available_bed_count <= posture_threshold(licensed_placement_bed_count):
        return "RESTRICTED"
    return "OPEN"


def expected_effective_available(
    licensed_placement_bed_count: int, raw_available_bed_count: int
) -> int:
    """Reproduce ``effective_available_bed_count`` of PRD 3.1."""
    posture = expected_posture(licensed_placement_bed_count, raw_available_bed_count)
    reserve = RESTRICTED_RESERVE_BEDS if posture == "RESTRICTED" else 0
    return max(0, raw_available_bed_count - reserve)


# ---------------------------------------------------------------------------
# Restraints (PRD 3.6)
# ---------------------------------------------------------------------------

#: Ordered-duration ceilings in minutes, keyed by minor status then type.
RESTRAINT_CEILING_MINUTES: Dict[bool, Dict[str, int]] = {
    False: {"PHYSICAL_HOLD": 60, "MECHANICAL_RESTRAINT": 240, "SECLUSION": 240},
    True: {"PHYSICAL_HOLD": 30, "MECHANICAL_RESTRAINT": 120, "SECLUSION": 120},
}

#: Monitoring cadence in minutes, by intervention type (PRD 3.6).
MONITORING_INTERVAL_MINUTES: Dict[str, int] = {
    "PHYSICAL_HOLD": 5,
    "MECHANICAL_RESTRAINT": 15,
    "SECLUSION": 15,
}

#: The face-to-face review is due sixty minutes after the start (PRD 3.6).
FACE_TO_FACE_WINDOW_MINUTES = 60

#: A sweep-expired unauthorized episode records this actual duration (PRD 3.6).
EXPIRED_UNAUTHORIZED_ACTUAL_MINUTES = 60

#: Observation staffing is billed in quarter hours (PRD 3.6).
QUARTER_HOUR_MINUTES = 15

#: Episode statuses that contribute observation quarter hours (PRD 3.6).
OBSERVATION_BILLABLE_STATUSES: Tuple[str, ...] = (
    "RELEASED",
    "DEBRIEFED",
    "EXPIRED_UNAUTHORIZED",
)

#: A debrief requires perfect grid compliance (PRD 3.6).
DEBRIEF_REQUIRED_GRID_COMPLIANCE_PCT = 100.0

#: The two compliance percentages are the only fractional figures (PRD 2.6).
COMPLIANCE_DECIMAL_PLACES = 1

# ---------------------------------------------------------------------------
# Hearings (PRD 3.4)
# ---------------------------------------------------------------------------

#: A hearing lasts exactly thirty or exactly sixty minutes (PRD 3.4).
HEARING_DURATIONS: Tuple[int, ...] = (30, 60)

#: Travel buffer applied on both sides of an advocate's docket (PRD 3.4).
DOCKET_BUFFER_MINUTES = 30

#: A petition may be continued only while its count is below this (PRD 3.4).
CONTINUANCE_LIMIT = 2

# ---------------------------------------------------------------------------
# Consents and discharge (PRD 3.7, 3.8)
# ---------------------------------------------------------------------------

#: An emergency-override consent expires this many hours after issue (PRD 3.7).
EMERGENCY_OVERRIDE_HOURS = 72

#: Surrogate scopes that authorize medication on a patient's behalf (PRD 3.7).
MEDICATION_AUTHORIZING_SCOPES: Tuple[str, ...] = ("MEDICATION_ONLY", "FULL")

#: A discharge request must be answered within this many business hours (3.8).
DISCHARGE_RESPONSE_BUSINESS_HOURS = 24

#: Follow-up guarantee base days, keyed by legal status then acuity tier (3.8).
FOLLOW_UP_BASE_DAYS: Dict[str, Dict[str, int]] = {
    "INVOLUNTARY": {"HIGH": 7, "MODERATE": 10, "LOW": 10},
    "VOLUNTARY": {"HIGH": 14, "MODERATE": 14, "LOW": 14},
}

#: A minor's guarantee window is capped at this many days (PRD 3.8).
MINOR_FOLLOW_UP_DAY_CAP = 5


def follow_up_guarantee_days(legal_status: str, tier: str, is_minor: bool) -> int:
    """Reproduce the follow-up guarantee table of PRD 3.8."""
    base = FOLLOW_UP_BASE_DAYS[legal_status][tier]
    if is_minor:
        return min(base, MINOR_FOLLOW_UP_DAY_CAP)
    return base


# ---------------------------------------------------------------------------
# Patients (PRD 3.2)
# ---------------------------------------------------------------------------

#: A patient is a minor below this age (PRD 3.2).
MINOR_AGE_CEILING = 18
PATIENT_MIN_AGE = 0
PATIENT_MAX_AGE = 120

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
MIN_OFFSET = 0


# ---------------------------------------------------------------------------
# Instant arithmetic (PRD 2.6, 3.3, 3.8)
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse any accepted UTC instant spelling into an aware ``datetime``."""
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def iso_ms(moment: datetime) -> str:
    """Render an instant the way the API does: UTC with three fractional digits."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def shift(value: str, *, hours: int = 0, minutes: int = 0, days: int = 0) -> str:
    """Return ``value`` moved by a wall-clock offset, in millisecond form."""
    return iso_ms(
        parse_instant(value) + timedelta(hours=hours, minutes=minutes, days=days)
    )


def is_calendar_day_open(moment: datetime) -> bool:
    """True when a date is neither a weekend nor one of the listed holidays."""
    if moment.weekday() >= 5:
        return False
    return moment.strftime("%Y-%m-%d") not in HOLIDAY_DATES


def roll_onto_court_calendar(value: str) -> str:
    """Roll a raw instant onto the court calendar exactly as PRD 2.6 directs.

    A weekend or holiday, or an instant after the close of the court day, moves
    to the next court day at ``09:00:00.000Z``; an instant before the open moves
    to that same date's opening; anything inside the window is unchanged.
    """
    moment = parse_instant(value)

    def opening(day: datetime) -> datetime:
        return day.replace(
            hour=COURT_DAY_OPEN_HOUR, minute=0, second=0, microsecond=0
        )

    def next_open_day(day: datetime) -> datetime:
        candidate = day + timedelta(days=1)
        while not is_calendar_day_open(candidate):
            candidate += timedelta(days=1)
        return opening(candidate)

    if not is_calendar_day_open(moment):
        return iso_ms(next_open_day(moment))
    if moment < opening(moment):
        return iso_ms(opening(moment))
    close = moment.replace(
        hour=COURT_DAY_CLOSE_HOUR, minute=0, second=0, microsecond=0
    )
    if moment > close:
        return iso_ms(next_open_day(moment))
    return iso_ms(moment)


def add_business_hours(value: str, hours: int = DISCHARGE_RESPONSE_BUSINESS_HOURS) -> str:
    """Advance an instant by whole business hours, day by day (PRD 3.8)."""
    moment = parse_instant(value)
    remaining = timedelta(hours=hours)

    def open_of(day: datetime) -> datetime:
        return day.replace(
            hour=BUSINESS_DAY_OPEN_HOUR, minute=0, second=0, microsecond=0
        )

    def close_of(day: datetime) -> datetime:
        return day.replace(
            hour=BUSINESS_DAY_CLOSE_HOUR, minute=0, second=0, microsecond=0
        )

    def advance_to_next_business_open(day: datetime) -> datetime:
        candidate = day + timedelta(days=1)
        while not is_calendar_day_open(candidate):
            candidate += timedelta(days=1)
        return open_of(candidate)

    if not is_calendar_day_open(moment) or moment >= close_of(moment):
        moment = advance_to_next_business_open(moment)
    elif moment < open_of(moment):
        moment = open_of(moment)

    while True:
        available = close_of(moment) - moment
        if remaining <= available:
            return iso_ms(moment + remaining)
        remaining -= available
        moment = advance_to_next_business_open(moment)


def round_half_up_one_dp(value: float) -> float:
    """Round to one decimal place, halves going up (PRD 2.6)."""
    from decimal import ROUND_HALF_UP, Decimal

    quantized = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(quantized)
