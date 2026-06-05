"""Shared parsing / validation helpers.

Centralizes the §2.5 / §2.10 well-formedness checks so every route raises
ERR_INVALID_REQUEST (400) consistently for missing/typed/enum/range failures,
and parses ISO 8601 datetimes uniformly.
"""
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err, ERR_INVALID_REQUEST


def parse_dt(value, field):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive datetimes are treated
    as UTC. Anything unparseable -> ERR_INVALID_REQUEST.
    """
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require(body, field):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, f"missing required field: {field}")
    return body[field]


def require_str(body, field, allow_empty=False):
    v = require(body, field)
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a string")
    if not allow_empty and v == "":
        raise err(ERR_INVALID_REQUEST, f"{field} must be non-empty")
    return v


def opt_str(body, field, default=None):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a string")
    return v


def require_enum(body, field, allowed):
    v = require_str(body, field, allow_empty=True)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, field, allowed, default=None):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        return default
    v = body[field]
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return v


def require_int(body, field):
    v = require(body, field)
    # bool is a subclass of int; reject it explicitly.
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an integer")
    return v


def opt_int(body, field, default=None):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an integer")
    return v


def require_fraction(body, field, lo_exclusive=False):
    """A number in [0,1] (or (0,1] when lo_exclusive)."""
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a number")
    if lo_exclusive:
        if not (0 < v <= 1):
            raise err(ERR_INVALID_REQUEST, f"{field} must be in (0, 1]")
    else:
        if not (0 <= v <= 1):
            raise err(ERR_INVALID_REQUEST, f"{field} must be in [0, 1]")
    return v


def opt_fraction(body, field, default=None):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a number")
    if not (0 <= v <= 1):
        raise err(ERR_INVALID_REQUEST, f"{field} must be in [0, 1]")
    return v


def require_bool(body, field, default=False):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return v


def validate_state_code(value, field="state_code"):
    """Exactly two uppercase letters."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{2}", value):
        raise err(ERR_INVALID_REQUEST, f"{field} must be exactly two uppercase letters")
    return value


def validate_naic(value):
    """Exactly five digits."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{5}", value):
        raise err(ERR_INVALID_REQUEST, "naic_code must be exactly 5 digits")
    return value


def round_half_up(value):
    """Round a numeric/Decimal to the nearest whole integer, halves up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def days_between(start_dt, end_dt):
    """Whole days from start (inclusive) to end (exclusive)."""
    delta = end_dt - start_dt
    return delta.days
