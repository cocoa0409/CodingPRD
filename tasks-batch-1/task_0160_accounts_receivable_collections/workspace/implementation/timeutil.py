"""Parsing helpers for ISO 8601 UTC datetime inputs.

Input datetimes (invoice_date, due_date, received_at, coverage_start/end,
pause_start/end, period_end, clock target) are ISO 8601 UTC strings. We parse
them to epoch milliseconds for all arithmetic (aging, window comparisons).
"""
import datetime

from errors import err, ERR_VALIDATION


def parse_iso_ms(value):
    """Parse an ISO 8601 datetime string into epoch milliseconds (UTC).

    Accepts a trailing 'Z' or an explicit offset. Raises ERR_VALIDATION on
    anything unparseable.
    """
    if not isinstance(value, str) or not value:
        raise err(ERR_VALIDATION, "invalid datetime")
    s = value.strip()
    # Python's fromisoformat (3.9) does not accept 'Z'; normalise it.
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        # Fall back to a couple of common explicit formats.
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.datetime.strptime(value.strip().rstrip("Zz"), fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            raise err(ERR_VALIDATION, "invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    return int(dt.timestamp() * 1000)
