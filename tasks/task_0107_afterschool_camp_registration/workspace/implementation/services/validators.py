"""Shape/type/range validators — produce ERR_VALIDATION when they fail."""

from errors import APIError


def require_field(body, field):
    if field not in body or body[field] is None:
        raise APIError("ERR_VALIDATION", f"Missing required field: {field}")
    return body[field]


def require_string(body, field, min_len=None, max_len=None):
    v = require_field(body, field)
    if not isinstance(v, str):
        raise APIError("ERR_VALIDATION", f"Field {field} must be a string.")
    if min_len is not None and len(v) < min_len:
        raise APIError("ERR_VALIDATION", f"Field {field} too short (min {min_len}).")
    if max_len is not None and len(v) > max_len:
        raise APIError("ERR_VALIDATION", f"Field {field} too long (max {max_len}).")
    return v


def optional_string(body, field, min_len=None, max_len=None, default=None):
    if field not in body or body[field] is None:
        return default
    return require_string(body, field, min_len=min_len, max_len=max_len)


def require_enum(body, field, allowed):
    v = require_field(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise APIError(
            "ERR_VALIDATION",
            f"Field {field} must be one of {sorted(allowed)}.",
        )
    return v


def optional_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return require_enum(body, field, allowed)


def require_int(body, field, minimum=None, maximum=None):
    v = require_field(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError("ERR_VALIDATION", f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        raise APIError("ERR_VALIDATION", f"Field {field} below minimum {minimum}.")
    if maximum is not None and v > maximum:
        raise APIError("ERR_VALIDATION", f"Field {field} above maximum {maximum}.")
    return v


def optional_int(body, field, minimum=None, maximum=None, default=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum=minimum, maximum=maximum)


def require_bool(body, field):
    v = require_field(body, field)
    if not isinstance(v, bool):
        raise APIError("ERR_VALIDATION", f"Field {field} must be a boolean.")
    return v


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    return require_bool(body, field)
