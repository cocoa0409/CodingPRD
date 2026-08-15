"""Time helpers: logical-clock timestamps, ISO-8601 parsing, date math.

Timestamps emitted on resources (created_at/updated_at and event stamps like
posted_at) are ISO 8601 UTC with three fractional digits (PRD §2.5), taken
from the logical clock. The meta envelope timestamp is also three-fractional-
digit UTC but reflects the real processing instant.
"""

import re
from datetime import datetime, date, timezone, timedelta


# Monotonic counter so multiple stamps within one request keep ascending order
# even though the logical clock only moves between requests.
_seq = {"n": 0}


def iso_ts_ms(dt=None):
    """ISO-8601 UTC with exactly three fractional digits, 'Z' suffix."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return "%s.%03dZ" % (base, dt.microsecond // 1000)


def logical_stamp():
    """Timestamp for resource fields: logical clock instant, 3 fractional
    digits, with a monotonically increasing millisecond bump so successive
    stamps inside one request never collide."""
    base = db_now()
    n = _seq["n"]
    _seq["n"] = n + 1
    return iso_ts_ms(base + timedelta(milliseconds=n % 1000))


def db_now():
    import db
    return db.now()


def parse_iso8601(s):
    """Parse an ISO-8601 datetime string into an aware UTC datetime.
    Accepts a trailing 'Z' or an explicit offset."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s):
    """Parse a strict YYYY-MM-DD calendar date."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        raise ValueError("not a YYYY-MM-DD date")
    return date.fromisoformat(s)


def add_years(d, years):
    """Advance a date by whole years; Feb-29 rolls to Mar-01 in non-leap
    years (PRD §3.4)."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 -> Mar 01 in a non-leap target year
        return date(d.year + years, 3, 1)


def window_index_for(joined, d):
    """0-based anniversary window index of date d for an agent who joined on
    `joined`: the greatest N with add_years(joined, N) <= d."""
    if d < joined:
        return None
    n = d.year - joined.year
    if add_years(joined, n) > d:
        n -= 1
    return n
