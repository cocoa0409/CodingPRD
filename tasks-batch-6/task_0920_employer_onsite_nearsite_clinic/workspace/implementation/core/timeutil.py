"""Date / instant parsing and rendering.

TIMESTAMP RENDERING RULE (uniform, enforced in exactly one place)
----------------------------------------------------------------
PRD 2.4 states `created_at` / `updated_at` are "ISO 8601 UTC timestamps
rendered with exactly three fractional-second digits and a trailing Z", and
PRD 3.7 states `sla_due_at` is "an ISO 8601 UTC instant with three fractional
digits".  There is no PRD sentence anywhere that asks the server to echo a
caller's literal datetime spelling back.

Therefore ONE canonical rendering is used for every datetime value this API
emits -- server stamps, computed instants and caller-supplied instants alike:

        YYYY-MM-DDTHH:MM:SS.mmmZ

Every inbound datetime is parsed and re-rendered through `fmt_instant` at
ingest, so a caller who posts `2026-05-04T08:00:00Z` reads back
`2026-05-04T08:00:00.000Z`, in exactly the same shape as `created_at`.  No
value in any payload mixes the two spellings.

Date-only values (`service_date`, `effective_date`, `period_start`, ...) stay
`YYYY-MM-DD`; they are not instants.
"""

import re
from datetime import date, datetime, timedelta, timezone

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt]"
    r"(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?"
    r"([Zz]|[+-]\d{2}:\d{2})$"
)

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

_HHMM_RE = re.compile(r"^(\d{2}):(\d{2})$")


def parse_instant(value):
    """Parse an ISO 8601 UTC instant.  Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, tzpart = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        dt = datetime(
            int(year), int(month), int(day),
            int(hour), int(minute), int(second), micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if tzpart not in ("Z", "z"):
        sign = 1 if tzpart[0] == "+" else -1
        offs = timedelta(hours=int(tzpart[1:3]), minutes=int(tzpart[4:6]))
        dt = dt - sign * offs
    return dt


def fmt_instant(dt):
    """Render an aware datetime in the one canonical shape."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, millis,
    )


def canonical_instant(value):
    """Parse then re-render an inbound instant; None when unparseable."""
    dt = parse_instant(value)
    if dt is None:
        return None
    return fmt_instant(dt)


def parse_date(value):
    """Parse an ISO YYYY-MM-DD date.  Returns a `date` or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_hhmm(value):
    """Parse an HH:MM 24h wall time into minutes past midnight, or None."""
    if not isinstance(value, str):
        return None
    m = _HHMM_RE.match(value.strip())
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if hh > 23 or mm > 59:
        return None
    return hh * 60 + mm


def date_of_instant(dt):
    return dt.date()


def instant_from_date_and_minutes(d, minutes):
    return datetime(
        d.year, d.month, d.day, minutes // 60, minutes % 60, 0, 0,
        tzinfo=timezone.utc,
    )


def iso_weekday(d):
    """ISO weekday: 1 = Monday .. 7 = Sunday."""
    return d.isoweekday()


def add_days(d, n):
    return d + timedelta(days=n)


def months_touched(start_d, end_d):
    """Distinct calendar months touched by the closed span [start, end]."""
    if end_d < start_d:
        return 0
    return (end_d.year - start_d.year) * 12 + (end_d.month - start_d.month) + 1
