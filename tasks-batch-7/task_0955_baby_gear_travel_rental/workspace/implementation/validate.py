"""Request-shape validators. All shape violations -> ERR_INVALID_REQUEST (400)."""
from errors import ApiError


def _bad(field, msg="invalid"):
    raise ApiError("ERR_INVALID_REQUEST", 400, f"{field}: {msg}")


def req_str(b, k):
    v = b.get(k)
    if not isinstance(v, str) or not v.strip():
        _bad(k, "required non-empty string")
    return v


def opt_str(b, k):
    v = b.get(k)
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip():
        _bad(k, "must be a non-empty string")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(b, k, min_v=None):
    v = b.get(k)
    if not _is_int(v):
        _bad(k, "required integer")
    if min_v is not None and v < min_v:
        _bad(k, f"must be >= {min_v}")
    return v


def opt_int(b, k, min_v=None):
    v = b.get(k)
    if v is None:
        return None
    if not _is_int(v):
        _bad(k, "must be an integer")
    if min_v is not None and v < min_v:
        _bad(k, f"must be >= {min_v}")
    return v


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_num(b, k):
    v = b.get(k)
    if not _is_num(v):
        _bad(k, "required number")
    return v


def opt_num(b, k):
    v = b.get(k)
    if v is None:
        return None
    if not _is_num(v):
        _bad(k, "must be a number")
    return v


def req_enum(b, k, allowed):
    v = b.get(k)
    if not isinstance(v, str) or v not in allowed:
        _bad(k, f"must be one of {sorted(allowed)}")
    return v


def opt_enum(b, k, allowed):
    v = b.get(k)
    if v is None:
        return None
    if not isinstance(v, str) or v not in allowed:
        _bad(k, f"must be one of {sorted(allowed)}")
    return v
