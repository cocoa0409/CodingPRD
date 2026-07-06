"""Input schema validators — priority 14 (ERR_INVALID_REQUEST)."""
from errors import raise_err, ERR_INVALID_REQUEST
from db import parse_iso


def require_fields(payload: dict, fields):
    if not isinstance(payload, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    for f in fields:
        if f not in payload or payload[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_str(payload: dict, field: str):
    v = payload.get(field)
    if not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return v


def optional_str(payload: dict, field: str):
    if field not in payload or payload[field] is None:
        return None
    v = payload[field]
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be a string")
    return v


def require_int(payload: dict, field: str):
    v = payload.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be integer")
    return v


def require_enum(payload: dict, field: str, allowed):
    v = payload.get(field)
    if v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}")
    return v


def optional_enum(payload: dict, field: str, allowed, default=None):
    if field not in payload or payload[field] is None:
        return default
    v = payload[field]
    if v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}")
    return v


def require_minute_multiple(payload: dict, field: str, lo: int = 15, hi: int = 480, allow_negative: bool = False):
    v = payload.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be an integer number of minutes")
    if allow_negative:
        if v == 0 or abs(v) % 15 != 0 or v < -hi or v > hi:
            raise_err(ERR_INVALID_REQUEST,
                      f"Field {field} must be a nonzero integer multiple of 15 in [{-hi}, {hi}]")
    else:
        if v < lo or v > hi or v % 15 != 0:
            raise_err(ERR_INVALID_REQUEST,
                      f"Field {field} must be an integer multiple of 15 in [{lo}, {hi}]")
    return v


def require_datetime(payload: dict, field: str) -> str:
    v = payload.get(field)
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 UTC string")
    try:
        parse_iso(v)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 UTC datetime")
    return v


def require_positive_int(payload: dict, field: str):
    v = require_int(payload, field)
    if v <= 0:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be a positive integer")
    return v


def require_ratio_two_dp(payload: dict, field: str, default: float = None):
    if field not in payload or payload[field] is None:
        if default is None:
            raise_err(ERR_INVALID_REQUEST, f"Field {field} is required")
        return default
    v = payload[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be a decimal number")
    # decimal in (0, 1], two decimal places
    if v <= 0 or v > 1:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be in (0, 1]")
    # Round to 2dp for storage; PRD says the stored value has 2dp.
    rounded = round(float(v) * 100) / 100.0
    if abs(rounded - v) > 1e-9:
        # More than 2dp of precision supplied — reject as invalid.
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must have two decimal places")
    return rounded
