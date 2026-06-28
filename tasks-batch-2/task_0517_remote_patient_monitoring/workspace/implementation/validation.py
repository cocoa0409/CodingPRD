"""Body-field type/enum/domain validation helpers (ERR_INVALID_REQUEST, 422)."""
import errors


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request(f"Missing required field: {name}.")
    return body[name]


def require_string(body, name, *, non_empty=True):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field {name} must be a string.")
    if non_empty and v.strip() == "":
        raise errors.invalid_request(f"Field {name} must be non-empty.")
    return v


def require_enum(body, name, allowed):
    v = require_field(body, name)
    if not isinstance(v, str) or v not in allowed:
        raise errors.invalid_request(
            f"Field {name} must be one of {sorted(allowed)}."
        )
    return v


def require_int(body, name, *, minimum=None, maximum=None):
    v = require_field(body, name)
    # Reject booleans (which are ints in Python) and floats.
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"Field {name} must be an integer.")
    if minimum is not None and v < minimum:
        raise errors.invalid_request(f"Field {name} must be >= {minimum}.")
    if maximum is not None and v > maximum:
        raise errors.invalid_request(f"Field {name} must be <= {maximum}.")
    return v


def require_number(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request(f"Field {name} must be a number.")
    return v


def require_datetime(body, name):
    from clock import parse_iso8601
    v = require_field(body, name)
    dt = parse_iso8601(v)
    if dt is None:
        raise errors.invalid_request(
            f"Field {name} must be an ISO-8601 datetime."
        )
    return dt


def optional_int(body, name, default, *, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return require_int(body, name, minimum=minimum, maximum=maximum)


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field {name} must be a boolean.")
    return v


def optional_number(body, name, default):
    if name not in body or body[name] is None:
        return default
    return require_number(body, name)


def optional_string(body, name, default=None, *, non_empty=False):
    if name not in body or body[name] is None:
        return default
    return require_string(body, name, non_empty=non_empty)
