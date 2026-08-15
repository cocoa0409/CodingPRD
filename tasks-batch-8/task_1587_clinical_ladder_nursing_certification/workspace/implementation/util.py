"""Shared parsing/validation helpers."""

from datetime import datetime, timezone

from errors import err_invalid_request


def parse_datetime(value, field):
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be an ISO 8601 datetime string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise err_invalid_request(f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_fields(payload, fields):
    if not isinstance(payload, dict):
        raise err_invalid_request("Request body must be a JSON object")
    for f in fields:
        if f not in payload or payload[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")


def require_string(payload, field):
    v = payload.get(field)
    if not isinstance(v, str) or not v:
        raise err_invalid_request(f"{field} must be a non-empty string")
    return v


def require_int(payload, field):
    v = payload.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{field} must be an integer")
    return v


def require_enum(payload, field, allowed):
    v = payload.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid_request(f"{field} must be one of {sorted(allowed)}")
    return v


def optional_string(payload, field):
    v = payload.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_invalid_request(f"{field} must be a string")
    return v
