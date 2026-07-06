"""Input field validation helpers -> ERR_INVALID_REQUEST (400) on failure."""
import errors
from clock import parse_iso


def _bad(msg):
    raise errors.err(errors.ERR_INVALID_REQUEST, msg)


def req_str(body, key, allow_empty=False):
    if key not in body:
        _bad(f"Missing required field: {key}")
    v = body[key]
    if not isinstance(v, str):
        _bad(f"Field {key} must be a string")
    if not allow_empty and v == "":
        _bad(f"Field {key} must not be empty")
    return v


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        _bad(f"Field {key} must be a string")
    return v


def req_enum(body, key, domain):
    v = req_str(body, key)
    if v not in domain:
        _bad(f"Field {key} must be one of {sorted(domain)}")
    return v


def opt_enum(body, key, domain, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if v not in domain:
        _bad(f"Field {key} must be one of {sorted(domain)}")
    return v


def _as_int(v, key):
    # reject bool (bool is subclass of int) and non-integers
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(f"Field {key} must be an integer")
    return v


def req_int(body, key, minimum=None):
    if key not in body:
        _bad(f"Missing required field: {key}")
    v = _as_int(body[key], key)
    if minimum is not None and v < minimum:
        _bad(f"Field {key} must be >= {minimum}")
    return v


def opt_int(body, key, default=None, minimum=None):
    if key not in body or body[key] is None:
        return default
    v = _as_int(body[key], key)
    if minimum is not None and v < minimum:
        _bad(f"Field {key} must be >= {minimum}")
    return v


def req_number(body, key, minimum=None):
    if key not in body:
        _bad(f"Missing required field: {key}")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(f"Field {key} must be a number")
    if minimum is not None and v < minimum:
        _bad(f"Field {key} must be >= {minimum}")
    return v


def opt_number(body, key, default=None, minimum=None):
    if key not in body or body[key] is None:
        return default
    return req_number(body, key, minimum=minimum)


def opt_bool(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        _bad(f"Field {key} must be a boolean")
    return v


def req_datetime(body, key):
    v = req_str(body, key)
    try:
        return parse_iso(v)
    except ValueError:
        _bad(f"Field {key} must be an ISO 8601 datetime")
