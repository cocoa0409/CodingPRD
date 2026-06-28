"""Shared request body validation helpers (ERR_INVALID_REQUEST / ERR_VALIDATION)."""
from errors import err, ERR_INVALID_REQUEST
from clock import parse_iso

STATE_CODES = {"CA", "NY", "TX", "FL", "WA", "IL"}
SPECIALTIES = {"ANXIETY", "DEPRESSION", "TRAUMA", "COUPLES", "GRIEF", "ADHD"}
SWITCH_REASONS = {"FIT", "AVAILABILITY", "CLINICAL", "OTHER"}
ESCALATION_SEVERITIES = {"ELEVATED", "ACUTE"}


def require_body(data):
    if data is None or not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_field(data, name):
    if name not in data or data[name] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return data[name]


def require_string(data, name, allow_empty=False, max_len=None):
    val = require_field(data, name)
    if not isinstance(val, str):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a string")
    if not allow_empty and len(val) == 0:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be non-empty")
    if max_len is not None and len(val) > max_len:
        raise err(ERR_INVALID_REQUEST, f"Field {name} exceeds max length {max_len}")
    return val


def require_int(data, name, minimum=None, maximum=None):
    val = require_field(data, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {name} below minimum {minimum}")
    if maximum is not None and val > maximum:
        raise err(ERR_INVALID_REQUEST, f"Field {name} above maximum {maximum}")
    return val


def optional_int(data, name, default, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        return default
    return require_int(data, name, minimum=minimum, maximum=maximum)


def require_bool(data, name, default=None):
    if name not in data or data[name] is None:
        if default is not None:
            return default
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    val = data[name]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return val


def require_enum(data, name, allowed):
    val = require_field(data, name)
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return val


def require_datetime(data, name):
    val = require_field(data, name)
    try:
        return parse_iso(val)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a valid ISO 8601 datetime")


def require_string_array_subset(data, name, allowed, non_empty=False):
    val = require_field(data, name)
    if not isinstance(val, list):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be an array")
    if non_empty and len(val) == 0:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be non-empty")
    for item in val:
        if item not in allowed:
            raise err(ERR_INVALID_REQUEST, f"Field {name} contains invalid value: {item}")
    return val
