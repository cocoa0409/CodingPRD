"""Body field validation helpers. Raises ERR_INVALID_REQUEST on malformed input."""
from errors import err

_INVALID = "ERR_INVALID_REQUEST"


def require_body(body):
    if body is None or not isinstance(body, dict):
        raise err(_INVALID, "Request body must be a JSON object")
    return body


def req_str(body, key, allow_empty=False):
    if key not in body or body[key] is None:
        raise err(_INVALID, f"{key} is required")
    v = body[key]
    if not isinstance(v, str):
        raise err(_INVALID, f"{key} must be a string")
    if not allow_empty and not v.strip():
        raise err(_INVALID, f"{key} must not be empty")
    return v


def req_int(body, key, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        raise err(_INVALID, f"{key} is required")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(_INVALID, f"{key} must be an integer")
    if minimum is not None and v < minimum:
        raise err(_INVALID, f"{key} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err(_INVALID, f"{key} must be <= {maximum}")
    return v


def opt_int(body, key, default, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        return default
    return req_int(body, key, minimum, maximum)


def req_number(body, key, minimum=None, maximum=None, min_exclusive=False, max_exclusive=False):
    if key not in body or body[key] is None:
        raise err(_INVALID, f"{key} is required")
    return _check_number(body[key], key, minimum, maximum, min_exclusive, max_exclusive)


def opt_number(body, key, default, minimum=None, maximum=None, min_exclusive=False, max_exclusive=False):
    if key not in body or body[key] is None:
        return default
    return _check_number(body[key], key, minimum, maximum, min_exclusive, max_exclusive)


def _check_number(v, key, minimum, maximum, min_exclusive, max_exclusive):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(_INVALID, f"{key} must be a number")
    if minimum is not None:
        if min_exclusive and v <= minimum:
            raise err(_INVALID, f"{key} must be > {minimum}")
        if not min_exclusive and v < minimum:
            raise err(_INVALID, f"{key} must be >= {minimum}")
    if maximum is not None:
        if max_exclusive and v >= maximum:
            raise err(_INVALID, f"{key} must be < {maximum}")
        if not max_exclusive and v > maximum:
            raise err(_INVALID, f"{key} must be <= {maximum}")
    return v


def req_enum(body, key, allowed):
    v = req_str(body, key)
    if v not in allowed:
        raise err(_INVALID, f"{key} must be one of {sorted(allowed)}")
    return v
