"""Shared helpers: time formatting, datetime parsing, money rounding, field validation."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err, ERR_INVALID_REQUEST


def iso_format(dt):
    """Format a system-minted datetime as ISO 8601 UTC with three fractional digits.

    Used for created_at / updated_at (PRD §2.4 — always three fractional digits).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_echo(dt):
    """Format an input-derived / computed datetime, preserving its precision.

    Input instants (pour_scheduled_start, completed_at, reading_at, window
    bounds) and datetimes computed from them in whole hours (cure_window_end)
    are echoed back in canonical UTC: a millisecond fraction is included only
    when non-zero, so a whole-second instant round-trips without a spurious
    ``.000``.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    if millis:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value, field_name):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime, or raise ERR_INVALID_REQUEST."""
    if not isinstance(value, str) or not value:
        raise err(ERR_INVALID_REQUEST, f"{field_name} must be an ISO 8601 datetime string")
    raw = value.strip()
    txt = raw
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"{field_name} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def money(value):
    """Round a numeric value to 2 dp using round-half-up, returning a float."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def D(value):
    return Decimal(str(value))


# ---- field validation helpers (ERR_INVALID_REQUEST, priority 5) ----

def require_string(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, f"{field} is required and must be a non-empty string")
    return val


def optional_string(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a string")
    return val


def require_number(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"{field} is required and must be a number")
    return val


def optional_number(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a number")
    return val


def require_int(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"{field} is required and must be an integer")
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return val


def optional_enum(body, field, allowed, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return val


def require_bool_optional(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return val
