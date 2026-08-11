"""Timestamp and parsing helpers. All temporal values are timezone-aware UTC
datetimes internally; serialization is ISO 8601 with three fractional digits
and a Z suffix (PRD §2.2/§2.5)."""
from datetime import datetime, timezone

from errors import ApiError, ERR_INVALID_REQUEST


def isoformat(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_datetime(value, field):
    """Parse an ISO 8601 timestamp; raise ERR_INVALID_REQUEST on bad input."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be an ISO 8601 timestamp string.")
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' is not a valid ISO 8601 timestamp.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_seconds(dt):
    """Truncate to second granularity (PRD §2.8 timestamp comparisons)."""
    return dt.replace(microsecond=0)


def require_str(body, field):
    value = body.get(field)
    if not isinstance(value, str) or value == "":
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' is required and must be a non-empty string.")
    return value


def optional_str(body, field):
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be a non-empty string when provided.")
    return value


def require_int(body, field, minimum=None):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' is required and must be an integer.")
    if minimum is not None and value < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be >= {minimum}.")
    return value


def optional_int(body, field, minimum=None):
    value = body.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be an integer when provided.")
    if minimum is not None and value < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be >= {minimum}.")
    return value


def optional_bool(body, field):
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be a boolean when provided.")
    return value


def require_enum(body, field, allowed):
    value = body.get(field)
    if value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            f"Field '{field}' is required and must be one of {sorted(allowed)}.",
        )
    return value


def optional_enum(body, field, allowed):
    value = body.get(field)
    if value is None:
        return None
    if value not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be one of {sorted(allowed)}.")
    return value
