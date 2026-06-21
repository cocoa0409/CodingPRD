"""ISO 8601 datetime parsing for period comparisons."""
from datetime import datetime, timezone

from errors import ApiError


def parse_iso(value, field="datetime"):
    """Parse an ISO 8601 string into an aware UTC datetime.

    Accepts trailing 'Z' and offsets. Naive inputs are treated as UTC.
    """
    if not isinstance(value, str) or not value:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 string")
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # tolerate date-only strings like 2025-05-01
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST",
                           f"Field {field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def in_period(ts_str, start_dt, end_dt):
    """True if ts_str (an ISO timestamp) falls in [start_dt, end_dt)."""
    t = parse_iso(ts_str)
    return start_dt <= t < end_dt


def periods_overlap(a_start, a_end, b_start, b_end):
    """Half-open overlap on [start, end). Touching endpoints do NOT overlap."""
    return a_start < b_end and b_start < a_end
