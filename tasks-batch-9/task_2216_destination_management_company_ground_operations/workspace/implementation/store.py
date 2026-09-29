"""In-memory data store, logical clock and row helpers.

Storage is process-local and starts completely empty on every boot: no entity
is ever seeded, preloaded or hardcoded here.  Tests build all state through
the declared API surface.
"""

import uuid
from datetime import datetime, timedelta, timezone

# The logical clock's start-up value, pinned by PRD section 2.4.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class DB:
    def __init__(self):
        self.programs = {}
        self.venues = {}
        self.suppliers = {}
        self.contracts = {}
        self.elements = {}
        self.permits = {}
        self.segments = {}
        self.manifest_entries = {}
        self.staff_members = {}
        self.staff_assignments = {}
        self.recon_lines = {}
        self.settlements = {}
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def clock_now():
    return db.clock


def set_clock(instant):
    # The clock itself is held as a plain instant so the stamps it feeds
    # (created_at, updated_at, submitted_at, ...) render in the canonical
    # ISO-8601-with-three-fractional-digits form of PRD section 2.4.
    db.clock = plain_dt(instant)
    return db.clock


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------

def utcnow():
    return datetime.now(timezone.utc)


class SuppliedInstant(datetime):
    """An instant parsed from a client-supplied field.

    It remembers the exact literal the client filed so the resource reads back
    exactly as it was written, and whether that literal named a bare calendar
    date rather than a full instant.
    """

    raw = None
    date_only = False


def plain_dt(value):
    """Strip any client-supplied literal, leaving a bare instant."""
    if value is None or type(value) is datetime:
        return value
    return datetime(
        value.year, value.month, value.day,
        value.hour, value.minute, value.second, value.microsecond,
        tzinfo=value.tzinfo,
    )


def _DATE_ONLY(text):
    if len(text) != 10:
        return False
    return text[4] == "-" and text[7] == "-" and text.replace("-", "").isdigit()


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits, e.g. ...T10:30:00.123Z

    A field whose value came straight from the client is echoed verbatim: the
    stored representation of a client-supplied date is the literal that was
    filed, not a re-rendered one.
    """
    if value is None:
        return None
    raw = getattr(value, "raw", None)
    if raw is not None:
        return raw
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second,
        value.microsecond // 1000,
    )


def parse_dt(raw):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    literal = raw.strip()
    if not literal:
        return None
    text = literal
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    supplied = SuppliedInstant(
        parsed.year, parsed.month, parsed.day,
        parsed.hour, parsed.minute, parsed.second, parsed.microsecond,
        tzinfo=parsed.tzinfo,
    )
    supplied.raw = literal
    supplied.date_only = _DATE_ONLY(literal)
    return supplied


def day_end(value):
    """The last instant of the calendar day a bare date names.

    A field filed as a bare `YYYY-MM-DD` names a whole day, so the day's final
    instant is what an inclusive upper bound has to compare against; a field
    filed as a full instant is already the bound it names.
    """
    if value is None or not getattr(value, "date_only", False):
        return value
    return plain_dt(value) + timedelta(days=1) - timedelta(microseconds=1)


def minutes_between(start, end):
    """Whole minutes from start to end (never negative)."""
    if start is None or end is None:
        return 0
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 60)


def whole_days_between(start, end):
    """Whole 24-hour days from start to end, fractional remainder discarded.

    Negative when end precedes start (floor semantics), per PRD section 3.7.
    """
    seconds = (end - start).total_seconds()
    import math
    return int(math.floor(seconds / 86400.0))


def plus_days(instant, days):
    return instant + timedelta(days=days)


def plus_minutes(instant, minutes):
    return instant + timedelta(minutes=minutes)


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------

def new_row(**fields):
    # PRD section 2.4: the server does not read wall-clock time, it reads the
    # logical clock, so the row-written stamp comes from the clock too.
    stamp = clock_now()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly one."""
    row["updated_at"] = clock_now()
    row["version"] = row.get("version", 1) + 1
    return row


def sort_rows(rows):
    """Default ordering: created_at ascending, insertion sequence as tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
