from datetime import datetime, timezone, timedelta
import errors
from errors import err


def parse_iso(s):
    """Parse an ISO 8601 timestamp string into a tz-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Returns None on failure.
    """
    if not isinstance(s, str):
        return None
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Add a whole number of calendar months to a tz-aware datetime.

    Clamps the day to the last valid day of the target month (e.g. Jan 31 + 1
    month -> Feb 28/29).
    """
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day to month length
    if month == 12:
        next_month_first = datetime(year + 1, 1, 1, tzinfo=dt.tzinfo)
    else:
        next_month_first = datetime(year, month + 1, 1, tzinfo=dt.tzinfo)
    last_day = (next_month_first - timedelta(days=1)).day
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def add_days(dt, days):
    return dt + timedelta(days=days)


# ---- request body field validation helpers (priority 5: ERR_INVALID_REQUEST) ----

def require_body(body):
    if not isinstance(body, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def req_str(body, field, min_len=1, max_len=None):
    v = body.get(field)
    if not isinstance(v, str) or isinstance(v, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a string.")
    if len(v) < min_len:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' is too short.")
    if max_len is not None and len(v) > max_len:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' is too long.")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be an integer.")
    if minimum is not None and v < minimum:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' is below minimum {minimum}.")
    if maximum is not None and v > maximum:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' is above maximum {maximum}.")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be one of {sorted(allowed)}.")
    return v


def req_datetime(body, field):
    v = body.get(field)
    dt = parse_iso(v)
    if dt is None:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 datetime.")
    return dt
