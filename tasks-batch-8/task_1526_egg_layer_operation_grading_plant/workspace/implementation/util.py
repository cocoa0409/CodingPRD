"""Date/decimal/validation helpers (PRD §2.6 rounding, §2.8 validation tiers)."""
import re
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError, ERR_VALIDATION

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Dates — every domain date is an ISO 8601 calendar date (PRD §2.4).
# ---------------------------------------------------------------------------
def parse_date(value):
    """Accept 'YYYY-MM-DD' or a full ISO 8601 datetime; return a date or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if DATE_RE.match(s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    iso = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.date()


def parse_instant(value):
    """Parse an ISO 8601 instant for the logical clock; return aware datetime."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if DATE_RE.match(s):
        try:
            d = date.fromisoformat(s)
        except ValueError:
            return None
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    iso = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dstr(d):
    """Serialize a date to YYYY-MM-DD (None passes through)."""
    if d is None:
        return None
    return d.isoformat()


# ---------------------------------------------------------------------------
# Decimal math — round-half-up everywhere (PRD §2.6); never float arithmetic.
# ---------------------------------------------------------------------------
def D(x):
    return Decimal(str(x))


def rhu(value, places):
    """round-half-up a Decimal/int to `places` decimal places -> Decimal."""
    if not isinstance(value, Decimal):
        value = D(value)
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """round-half-up to a whole integer -> int."""
    return int(rhu(value, 0))


def rhu_float(value, places):
    return float(rhu(value, places))


# ---------------------------------------------------------------------------
# Request-field validators (tier 5 schema). All raise ERR_VALIDATION (400).
# ---------------------------------------------------------------------------
def _present(body, field):
    return field in body and body[field] is not None


def req_str(body, field):
    if not _present(body, field):
        raise ApiError(ERR_VALIDATION, 400, f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_VALIDATION, 400, f"Field {field} must be a non-empty string")
    return v


def opt_str(body, field):
    if not _present(body, field):
        return None
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_VALIDATION, 400, f"Field {field} must be a non-empty string")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_int(body, field, min_v=None, max_v=None):
    if not _present(body, field):
        raise ApiError(ERR_VALIDATION, 400, f"Missing required field: {field}")
    v = body[field]
    if not _is_int(v):
        raise ApiError(ERR_VALIDATION, 400, f"Field {field} must be an integer")
    if min_v is not None and v < min_v:
        raise ApiError(ERR_VALIDATION, 400, f"Field {field} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise ApiError(ERR_VALIDATION, 400, f"Field {field} must be <= {max_v}")
    return v


def opt_int(body, field, min_v=None, max_v=None):
    if not _present(body, field):
        return None
    return req_int(body, field, min_v=min_v, max_v=max_v)


def req_num(body, field, min_v=None):
    if not _present(body, field):
        raise ApiError(ERR_VALIDATION, 400, f"Missing required field: {field}")
    v = body[field]
    if not _is_num(v):
        raise ApiError(ERR_VALIDATION, 400, f"Field {field} must be a number")
    if min_v is not None and v < min_v:
        raise ApiError(ERR_VALIDATION, 400, f"Field {field} must be >= {min_v}")
    return v


def req_enum(body, field, allowed):
    if not _present(body, field):
        raise ApiError(ERR_VALIDATION, 400, f"Missing required field: {field}")
    v = body[field]
    if v not in allowed:
        raise ApiError(ERR_VALIDATION, 400, f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_date(body, field):
    if not _present(body, field):
        raise ApiError(ERR_VALIDATION, 400, f"Missing required field: {field}")
    d = parse_date(body[field])
    if d is None:
        raise ApiError(ERR_VALIDATION, 400, f"Field {field} must be an ISO 8601 date")
    return d
