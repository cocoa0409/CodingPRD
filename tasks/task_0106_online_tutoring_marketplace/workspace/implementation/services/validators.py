"""Body validation helpers — translate body parse/type errors into ERR_VALIDATION."""

import re

from errors import APIError

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
)
SUBJECT_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,29}$")


def require_body(data):
    if not isinstance(data, dict):
        raise APIError("ERR_VALIDATION", "Request body must be a JSON object.")


def require_field(body, key):
    if key not in body or body[key] is None:
        raise APIError("ERR_VALIDATION", f"Field '{key}' is required.")
    return body[key]


def require_string(body, key, min_len=None, max_len=None):
    value = require_field(body, key)
    if not isinstance(value, str):
        raise APIError("ERR_VALIDATION", f"Field '{key}' must be a string.")
    if min_len is not None and len(value) < min_len:
        raise APIError("ERR_VALIDATION", f"Field '{key}' is too short.")
    if max_len is not None and len(value) > max_len:
        raise APIError("ERR_VALIDATION", f"Field '{key}' is too long.")
    return value


def optional_string(body, key, min_len=None, max_len=None):
    if key not in body or body[key] is None:
        return None
    return require_string(body, key, min_len, max_len)


def require_int(body, key, min_value=None, max_value=None):
    value = require_field(body, key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise APIError("ERR_VALIDATION", f"Field '{key}' must be an integer.")
    if min_value is not None and value < min_value:
        raise APIError("ERR_VALIDATION", f"Field '{key}' is below minimum.")
    if max_value is not None and value > max_value:
        raise APIError("ERR_VALIDATION", f"Field '{key}' is above maximum.")
    return value


def optional_int(body, key, min_value=None, max_value=None):
    if key not in body or body[key] is None:
        return None
    return require_int(body, key, min_value, max_value)


def require_bool(body, key, default=False):
    if key not in body or body[key] is None:
        return default
    value = body[key]
    if not isinstance(value, bool):
        raise APIError("ERR_VALIDATION", f"Field '{key}' must be a boolean.")
    return value


def require_enum(body, key, allowed):
    value = require_string(body, key)
    if value not in allowed:
        raise APIError("ERR_VALIDATION", f"Field '{key}' must be one of {sorted(allowed)}.")
    return value


def optional_enum(body, key, allowed):
    if key not in body or body[key] is None:
        return None
    return require_enum(body, key, allowed)


def require_email(body, key, max_len=254):
    value = require_string(body, key, min_len=3, max_len=max_len)
    if not EMAIL_RE.match(value):
        raise APIError("ERR_VALIDATION", f"Field '{key}' is not a valid email.")
    return value


def require_subject_code(body, key):
    value = require_string(body, key)
    if not SUBJECT_CODE_RE.match(value):
        raise APIError("ERR_VALIDATION", f"Field '{key}' is not a valid subject code.")
    return value
