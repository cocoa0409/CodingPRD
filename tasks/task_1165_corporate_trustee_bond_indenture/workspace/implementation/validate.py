"""Shape validation helpers (rule 26, checked last) and date/number utilities."""
from datetime import date, datetime, timezone

from errors import raise_err, ERR_INVALID_REQUEST


def parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s[:10]) if len(s) >= 10 and s[4] == "-" else None
    except ValueError:
        return None


def parse_date_strict(s):
    """Strict YYYY-MM-DD date parsing."""
    if not isinstance(s, str) or len(s) != 10:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_datetime(s):
    """Parse ISO 8601 datetime, 'Z' or offset; naive values assumed UTC."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(b, k):
    v = b.get(k)
    if not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, "Missing or invalid required field: %s" % k)
    return v


def opt_str(b, k):
    v = b.get(k)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "Field must be a string: %s" % k)
    return v


def req_int(b, k):
    v = b.get(k)
    if not is_int(v):
        raise_err(ERR_INVALID_REQUEST, "Missing or invalid integer field: %s" % k)
    return v


def opt_int(b, k, default=None):
    v = b.get(k)
    if v is None:
        return default
    if not is_int(v):
        raise_err(ERR_INVALID_REQUEST, "Field must be an integer: %s" % k)
    return v


def req_num(b, k):
    v = b.get(k)
    if not is_num(v):
        raise_err(ERR_INVALID_REQUEST, "Missing or invalid numeric field: %s" % k)
    return v


def opt_num(b, k):
    v = b.get(k)
    if v is None:
        return None
    if not is_num(v):
        raise_err(ERR_INVALID_REQUEST, "Field must be a number: %s" % k)
    return v


def req_enum(b, k, values):
    v = b.get(k)
    if v not in values:
        raise_err(ERR_INVALID_REQUEST,
                  "Field %s must be one of %s" % (k, ", ".join(values)))
    return v


def opt_enum(b, k, values):
    v = b.get(k)
    if v is None:
        return None
    if v not in values:
        raise_err(ERR_INVALID_REQUEST,
                  "Field %s must be one of %s" % (k, ", ".join(values)))
    return v


def req_date(b, k):
    v = b.get(k)
    d = parse_date_strict(v)
    if d is None:
        raise_err(ERR_INVALID_REQUEST, "Field %s must be an ISO date (YYYY-MM-DD)" % k)
    return v


def opt_date(b, k):
    v = b.get(k)
    if v is None:
        return None
    if parse_date_strict(v) is None:
        raise_err(ERR_INVALID_REQUEST, "Field %s must be an ISO date (YYYY-MM-DD)" % k)
    return v


def req_datetime(b, k):
    v = b.get(k)
    if parse_datetime(v) is None:
        raise_err(ERR_INVALID_REQUEST, "Field %s must be an ISO 8601 datetime" % k)
    return v


def add_months(d, months):
    """Add calendar months to a date, clamping the day to month length."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    days_in = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
               31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(y, m, min(d.day, days_in[m - 1]))


def round_half_up_ratio(num, den):
    """floor(num/den + 1/2) — exact round-half-up for integer num/den."""
    return (2 * num + den) // (2 * den)
