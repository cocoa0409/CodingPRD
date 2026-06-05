from datetime import datetime, timezone
import errors
from errors import err


def parse_iso(s):
    """Parse an ISO 8601 timestamp (or bare date) into a tz-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset, and a bare date (YYYY-MM-DD).
    Returns None on failure.
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


def parse_date(s):
    """Parse a bare ISO date (YYYY-MM-DD) into a date object. Returns None on
    failure. Accepts a full datetime too, taking its date part."""
    dt = parse_iso(s)
    if dt is None:
        return None
    return dt.date()


# ---- request body field validation helpers (ERR_INVALID_REQUEST / 400) ----

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


def req_number(body, field, minimum=None, maximum=None,
               strict_min=False, strict_max=False):
    """Accept int or float (but not bool)."""
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a number.")
    if minimum is not None:
        if strict_min and not (v > minimum):
            raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be greater than {minimum}.")
        if not strict_min and v < minimum:
            raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' is below minimum {minimum}.")
    if maximum is not None:
        if strict_max and not (v < maximum):
            raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be less than {maximum}.")
        if not strict_max and v > maximum:
            raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' is above maximum {maximum}.")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be one of {sorted(allowed)}.")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def req_iso_date(body, field):
    """Require a parseable ISO date/datetime string; returns the raw string."""
    v = body.get(field)
    if parse_date(v) is None:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO date.")
    return v


def req_datetime(body, field):
    """Require a parseable ISO 8601 datetime string; returns the raw string."""
    v = body.get(field)
    if parse_iso(v) is None:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 datetime.")
    return v


def req_fk(body, field):
    """A foreign-key id must be a non-empty string. Type/presence failure is a
    body-validation problem (ERR_INVALID_REQUEST); whether it resolves to a real
    record is an existence problem checked later (ERR_NOT_FOUND)."""
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a non-empty string.")
    return v


def opt_fk(body, field):
    if field not in body or body.get(field) is None:
        return None
    return req_fk(body, field)
