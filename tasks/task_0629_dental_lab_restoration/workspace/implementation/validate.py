"""Request-body schema helpers (lowest-priority gate -> ERR_INVALID_REQUEST 400, PRD §2.9)."""
from datetime import datetime, timezone

import errors
from errors import err


def get_body():
    """Return parsed JSON body as a dict; treat missing/non-object as {}."""
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_INVALID_REQUEST, f"Missing or invalid field '{field}'.")
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be one of {sorted(allowed)}.")
    return val


def optional_enum(body, field, allowed, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be one of {sorted(allowed)}.")
    return val


def require_int(body, field, minimum=None):
    val = body.get(field)
    # bool is a subclass of int — reject it explicitly
    if not isinstance(val, int) or isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be an integer.")
    if minimum is not None and val < minimum:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be >= {minimum}.")
    return val


def optional_int(body, field, default, minimum=None):
    if field not in body or body.get(field) is None:
        return default
    return require_int(body, field, minimum)


def optional_bool(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a boolean.")
    return val


def require_datetime(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_INVALID_REQUEST, f"Missing or invalid field '{field}'.")
    return parse_iso(val, field)


def parse_iso(value, field="timestamp"):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if not isinstance(value, str):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 string.")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' is not a valid ISO 8601 instant.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
