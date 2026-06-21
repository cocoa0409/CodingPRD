"""Server clock and ISO 8601 datetime helpers.

Timestamps are ISO 8601 UTC with exactly three fractional digits + 'Z'
(PRD §2.2 / §2.4). The server's "now" tracks real wall-clock UTC; there is no
clock-override endpoint in this PRD.
"""
import datetime


def current_utc():
    """Return current server UTC as a tz-aware datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


def fmt(dt):
    """Format a tz-aware datetime as ISO8601 UTC with 3 fractional digits + Z."""
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def now_iso():
    return fmt(current_utc())


def parse_iso(s):
    """Parse an ISO8601 datetime string into a tz-aware UTC datetime.

    Accepts trailing 'Z' and optional fractional seconds / offsets. Naive
    datetimes are assumed to be UTC. Raises ValueError on bad input.
    """
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    text = s.strip()
    if not text:
        raise ValueError("empty datetime string")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def to_utc_date(dt):
    """Return the UTC calendar date of a tz-aware datetime."""
    return dt.astimezone(datetime.timezone.utc).date()
