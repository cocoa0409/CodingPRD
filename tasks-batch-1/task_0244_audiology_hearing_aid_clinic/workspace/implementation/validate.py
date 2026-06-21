"""Body field validation helpers (ERR_INVALID_REQUEST, priority 20 / §2.3).

These enforce presence, type, enum, and range constraints declared in §1.1.
Booleans are NOT accepted where an integer is required (bool is an int
subclass in Python, so we reject it explicitly).
"""

import errors


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def require_str(body, field, allow_blank=False):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"{field} is required.")
    v = body[field]
    if not isinstance(v, str):
        raise errors.invalid_request(f"{field} must be a string.")
    if not allow_blank and v.strip() == "":
        raise errors.invalid_request(f"{field} must not be blank.")
    return v


def optional_str(body, field):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, str):
        raise errors.invalid_request(f"{field} must be a string.")
    return v


def require_int(body, field, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"{field} is required.")
    v = body[field]
    if not _is_int(v):
        raise errors.invalid_request(f"{field} must be an integer.")
    if minimum is not None and v < minimum:
        raise errors.invalid_request(f"{field} must be >= {minimum}.")
    if maximum is not None and v > maximum:
        raise errors.invalid_request(f"{field} must be <= {maximum}.")
    return v


def require_enum(body, field, choices):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"{field} is required.")
    v = body[field]
    if v not in choices:
        raise errors.invalid_request(f"{field} must be one of {sorted(choices)}.")
    return v


def require_in_set(body, field, allowed):
    """Required integer whose value must be exactly one of an allowed set
    (e.g. ear_count in {1,2}, cadence_days in {30,60,90})."""
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"{field} is required.")
    v = body[field]
    if not _is_int(v) or v not in allowed:
        raise errors.invalid_request(f"{field} must be one of {sorted(allowed)}.")
    return v


def require_fraction(body, field):
    """coinsurance_pct: number with 0 <= v < 1."""
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"{field} is required.")
    v = body[field]
    if not _is_num(v):
        raise errors.invalid_request(f"{field} must be a number.")
    if not (0 <= v < 1):
        raise errors.invalid_request(f"{field} must satisfy 0 <= {field} < 1.")
    return float(v)


def require_date(body, field):
    """Required YYYY-MM-DD date string."""
    from timeutil import parse_date
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"{field} is required.")
    v = body[field]
    if not isinstance(v, str) or parse_date(v) is None:
        raise errors.invalid_request(f"{field} must be a YYYY-MM-DD date.")
    return v
