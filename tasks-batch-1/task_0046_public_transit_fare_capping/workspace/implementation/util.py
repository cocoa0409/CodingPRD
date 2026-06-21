from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP
import errors
from errors import err


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def parse_iso_datetime(s):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime.

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


def parse_iso_date(s):
    """Parse an ISO 8601 date (YYYY-MM-DD). Returns a date, or None on failure."""
    if not isinstance(s, str):
        return None
    raw = s.strip()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def fare_day(dt):
    """The calendar date (UTC) of a tapped_at instant (PRD §2.8)."""
    return dt.astimezone(timezone.utc).date()


def fare_day_month(dt):
    """The YYYY-MM of a tapped_at instant's fare day."""
    d = fare_day(dt)
    return f"{d.year:04d}-{d.month:02d}"


def add_days(d, days):
    return d + timedelta(days=days)


# ---------------------------------------------------------------------------
# Money / rounding (PRD §2.5): integer cents, round-half-up at each per-ride
# percentage multiplication.
# ---------------------------------------------------------------------------

def round_half_up_cents(value):
    """Round a numeric value to the nearest whole cent using round-half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of_cents(cents, pct):
    """cents * pct, rounded half-up to a whole cent (per-ride rounding)."""
    return int((Decimal(int(cents)) * Decimal(str(pct))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def scale_cents_by_discount(cents, eff_discount_pct):
    """cents * (1 - eff_discount_pct), rounded half-up (per-ride rounding)."""
    factor = Decimal("1") - Decimal(str(eff_discount_pct))
    return int((Decimal(int(cents)) * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Request body field validation helpers (priority 5: ERR_INVALID_REQUEST).
# ---------------------------------------------------------------------------

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


def opt_int(body, field, minimum=None, maximum=None, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum, maximum)


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be one of {sorted(allowed)}.")
    return v


def opt_enum(body, field, allowed, default):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def req_number(body, field, minimum=None, maximum=None,
               min_inclusive=True, max_inclusive=True):
    """A numeric fraction (int or float), e.g. a discount pct between 0 and 1."""
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a number.")
    if minimum is not None:
        if min_inclusive and v < minimum:
            raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' below minimum {minimum}.")
        if not min_inclusive and v <= minimum:
            raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must exceed {minimum}.")
    if maximum is not None:
        if max_inclusive and v > maximum:
            raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' above maximum {maximum}.")
        if not max_inclusive and v >= maximum:
            raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be below {maximum}.")
    return v


def opt_number(body, field, minimum=None, maximum=None,
               min_inclusive=True, max_inclusive=True, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_number(body, field, minimum, maximum, min_inclusive, max_inclusive)


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a boolean.")
    return v


def opt_bool(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    return req_bool(body, field)


def req_datetime(body, field):
    dt = parse_iso_datetime(body.get(field))
    if dt is None:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 datetime.")
    return dt


def req_date_str(body, field):
    """A YYYY-MM-DD date string; returns (raw_string, date)."""
    v = body.get(field)
    d = parse_iso_date(v)
    if d is None:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a YYYY-MM-DD date.")
    return v.strip(), d


def req_month_str(body, field):
    """A YYYY-MM month string; returns the normalized string."""
    v = body.get(field)
    if not isinstance(v, str):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a YYYY-MM month string.")
    raw = v.strip()
    parts = raw.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a YYYY-MM month string.")
    try:
        year = int(parts[0])
        month = int(parts[1])
    except ValueError:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a YYYY-MM month string.")
    if month < 1 or month > 12:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' month component out of range.")
    return f"{year:04d}-{month:02d}"
