"""The logical clock (PRD 2.5) and every timestamp / date helper.

TIMESTAMP RENDERING RULE (single, explicit, applied everywhere):

  * Server-written instants (`created_at`, `updated_at`, `effective_at`,
    `activated_at`, `withdrawn_at`, `revoked_at`, `completed_at`, `sent_at`,
    `acknowledged_at`, `generated_at`, `api_request_timestamp`) are rendered
    from the logical clock in exactly ONE form: ``YYYY-MM-DDTHH:MM:SS.mmmZ``
    (ISO 8601 UTC, three fractional digits) as PRD section 2.4 requires.

  * Caller-supplied instants and dates (`scheduled_start_at`, `start_at`,
    `end_at`, `administered_date`, `report_received_date`, `date_of_birth`,
    `period_start_date`, `period_end_date`, and the clock's own `to_iso8601`)
    are stored and echoed back **verbatim** — byte for byte as the client sent
    them.  They are parsed for comparison but never re-rendered.

  * Derived dates (`earliest_valid_date`, `strict_earliest_valid_date`,
    `determination_date`, `valid_until`, `unrestricted_valid_until`) are
    rendered as bare ``YYYY-MM-DD``.  `expires_at` is the literal school-year
    end instant string from PRD section 2.5.
"""

import re
from datetime import datetime, timedelta, timezone

import config

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class _Clock(object):
    """Set to the PRD default at import; never reads the host wall clock."""

    def __init__(self):
        self.raw = None
        self.dt = None

    def reset(self):
        self.raw = config.DEFAULT_CLOCK_UTC
        self.dt = parse_datetime(config.DEFAULT_CLOCK_UTC)

    def set(self, raw, dt):
        self.raw = raw
        self.dt = dt


CLOCK = _Clock()


def now_dt():
    """Current logical instant as an aware UTC datetime."""
    return CLOCK.dt


def now_date():
    """Current logical clock date."""
    return CLOCK.dt.date()


def now_iso():
    """Server-written timestamp form: ISO 8601 UTC, exactly 3 fractional digits."""
    return format_instant(CLOCK.dt)


def current_utc_raw():
    """The clock value as the caller last supplied it (verbatim echo)."""
    return CLOCK.raw


def format_instant(dt):
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def format_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_datetime(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a bare ``YYYY-MM-DD`` calendar date.  Returns a date or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _ISO_DATE_RE.match(text):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def add_days(d, days):
    return d + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def whole_years_between(born, on_date):
    """Completed whole years from `born` to `on_date`."""
    years = on_date.year - born.year
    if (on_date.month, on_date.day) < (born.month, born.day):
        years -= 1
    return years


def current_school_year(d=None):
    """PRD 2.5: month >= 8 -> "<Y>-<Y+1>", else "<Y-1>-<Y>"."""
    if d is None:
        d = now_date()
    if d.month >= 8:
        return "%d-%d" % (d.year, d.year + 1)
    return "%d-%d" % (d.year - 1, d.year)


def school_year_end_instant(school_year):
    return config.SCHOOL_YEARS[school_year]["end_instant"]


def school_year_end_date(school_year):
    return config.SCHOOL_YEARS[school_year]["end_date"]


CLOCK.reset()
