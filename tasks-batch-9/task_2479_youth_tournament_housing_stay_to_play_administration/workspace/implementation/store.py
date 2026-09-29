"""In-memory data store, the logical UTC clock, and id / timestamp helpers.

The store is a set of plain dicts keyed by id.  It starts completely empty on
every boot: nothing is seeded, preloaded or hardcoded here.  Every row is
created by a client through one of the declared endpoints.
"""

import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone

# PRD 2.5 — the logical clock's startup value.
LOGICAL_CLOCK_START = "2026-08-01T00:00:00Z"

_COLLECTIONS = (
    "tournaments",
    "hotels",
    "teams",
    "contracts",
    "room_blocks",
    "registrations",
    "bookings",
    "rooming_entries",
    "exception_requests",
    "complaints",
    "invoices",
    "distributions",
    "actualizations",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class _Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in _COLLECTIONS:
            setattr(self, name, {})
        self.current_utc = parse_datetime(LOGICAL_CLOCK_START)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    """A UUID string with no type prefix and no client-supplied component."""
    return str(uuid.uuid4())


def new_request_id():
    body = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20))
    return "req_" + body


def now():
    """The logical clock instant, as an aware UTC datetime."""
    return db.current_utc


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def now_iso():
    return fmt_dt(db.current_utc)


def parse_datetime(value):
    """Parse an ISO 8601 datetime (or bare calendar date) into aware UTC.

    Returns None when the value is not a well-formed ISO 8601 instant.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if _DATE_RE.match(text):
        try:
            d = date.fromisoformat(text)
        except ValueError:
            return None
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    normalised = text
    if normalised.endswith(("Z", "z")):
        normalised = normalised[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date.  Returns None when malformed."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def day_span(start, end):
    """Whole days from start up to but not including end (half-open)."""
    return (end - start).days


def nights_between(start, end):
    """The list of night-start dates in the half-open range [start, end)."""
    # a night is identified by the calendar day it begins on
    out = []
    cursor = start
    while cursor < end:
        out.append(cursor)
        cursor = cursor + timedelta(days=1)
    return out


def midnight(day):
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


db = _Store()
