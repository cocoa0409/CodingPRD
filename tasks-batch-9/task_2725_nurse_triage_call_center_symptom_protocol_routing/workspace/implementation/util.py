"""Shared primitives: timestamp formatting/parsing, ordinals, rounding.

Every "now" in this system comes from the logical clock (store.clock); nothing
here ever consults the host wall clock.
"""
import math
import re
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Severity scales (PRD 3.6 / 3.10)
# ---------------------------------------------------------------------------
LEVEL_ORDINAL = {
    "EMERGENCY_911": 5,
    "ED_NOW": 4,
    "URGENT_CARE_24H": 3,
    "OFFICE_APPT_72H": 2,
    "HOME_CARE": 1,
}
DISPOSITION_LEVELS = ["EMERGENCY_911", "ED_NOW", "URGENT_CARE_24H",
                     "OFFICE_APPT_72H", "HOME_CARE"]

OUTCOME_ORDINAL = {
    "ED_ADMITTED": 5,
    "ED_TREATED_RELEASED": 4,
    "URGENT_CARE_VISIT": 3,
    "OFFICE_VISIT": 2,
    "SELF_CARE_RESOLVED": 1,
}
REPORTED_OUTCOMES = list(OUTCOME_ORDINAL.keys())
OUTCOME_SOURCES = ["EHR_CLAIM", "PATIENT_REPORT", "ED_FEED"]

OVERRIDE_REASON_CODES = ["CALLER_REFUSED_ED", "TRANSPORT_UNAVAILABLE",
                        "CLINICIAN_DIRECTED", "PROTOCOL_MISMATCH",
                        "LANGUAGE_BARRIER"]

HHMM_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
STATE_RE = re.compile(r"^[A-Z]{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PROTOCOL_CODE_RE = re.compile(r"^[A-Z0-9_]{3,20}$")
PSAP_CODE_RE = re.compile(r"^[A-Z0-9-]{3,20}$")


# ---------------------------------------------------------------------------
# Timestamps — ISO 8601 UTC with exactly three fractional digits (PRD 2.5)
# ---------------------------------------------------------------------------
def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO-8601 UTC instant. Returns a naive UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith("z") or candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def parse_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def hhmm_to_minutes(text):
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def full_years_between(dob, reference_date):
    """Full years elapsed from dob to reference_date."""
    years = reference_date.year - dob.year
    if (reference_date.month, reference_date.day) < (dob.month, dob.day):
        years -= 1
    return years


def whole_minutes(start, end):
    if end <= start:
        return 0
    return int((end - start).total_seconds() // 60)


def overlap_minutes(a_start, a_end, b_start, b_end):
    """Whole minutes of overlap between two half-open intervals."""
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if end <= start:
        return 0
    return int((end - start).total_seconds() // 60)


# ---------------------------------------------------------------------------
# Rounding — half up, never banker's (PRD 2.8)
# ---------------------------------------------------------------------------
def round_half_up_int(value):
    """value may be int/float/Decimal/Fraction-ish; returns int."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_cents(numerator, denominator):
    """round_half_up(numerator / denominator) -> int cents."""
    quotient = Decimal(numerator) / Decimal(denominator)
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(numerator, denominator):
    """round_half_up(numerator / denominator, 1) -> float with one decimal."""
    quotient = Decimal(numerator) / Decimal(denominator)
    return float(quotient.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


def ceil_to_multiple(value, multiple):
    return int(math.ceil(value / float(multiple))) * multiple


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def next_day_at(reference_dt, hhmm):
    """Calendar date of reference_dt plus one day, at the given UTC HH:MM."""
    minutes = hhmm_to_minutes(hhmm)
    day = reference_dt.date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day) + timedelta(minutes=minutes)
