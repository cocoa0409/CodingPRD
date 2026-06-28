"""Logical clock used for date-bearing event stamps (discovered_on / reported_8823_on).

Startup default is 2026-01-01T00:00:00Z. Before any explicit set, the clock reads
exactly this default and never the real wall-clock time.
"""

_DEFAULT = "2026-01-01T00:00:00.000Z"


class Clock:
    def __init__(self):
        self._current = _DEFAULT

    def now_iso(self):
        return self._current

    def set(self, iso):
        self._current = _normalize_iso(iso)


def _normalize_iso(iso):
    """Normalize an ISO8601 instant to UTC with three fractional digits."""
    if iso is None:
        return _DEFAULT
    s = str(iso).strip()
    # Accept trailing Z or +00:00; strip to a datetime and re-emit with millis.
    from datetime import datetime, timezone

    candidate = s
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    except (ValueError, TypeError):
        # Fall back to storing the raw string if it is not parseable.
        return s


clock = Clock()
