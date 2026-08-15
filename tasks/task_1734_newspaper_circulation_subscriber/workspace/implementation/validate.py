"""Request-shape validators. All shape violations -> ERR_INVALID_REQUEST (400)."""
from decimal import Decimal, InvalidOperation

from errors import ApiError
from util import parse_date


def _bad(field, msg="invalid"):
    raise ApiError("ERR_INVALID_REQUEST", 400, f"{field}: {msg}")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


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


def req_int(b, k, min_v=None, max_v=None):
    v = b.get(k)
    if not is_int(v):
        _bad(k, "required integer")
    if min_v is not None and v < min_v:
        _bad(k, f"must be >= {min_v}")
    if max_v is not None and v > max_v:
        _bad(k, f"must be <= {max_v}")
    return v


def opt_int(b, k, min_v=None):
    v = b.get(k)
    if v is None:
        return None
    if not is_int(v):
        _bad(k, "must be an integer")
    if min_v is not None and v < min_v:
        _bad(k, f"must be >= {min_v}")
    return v


def req_decimal(b, k, min_v=None, max_v=None):
    v = b.get(k)
    if not is_num(v):
        _bad(k, "required number")
    try:
        dv = Decimal(str(v))
    except InvalidOperation:
        _bad(k, "must be a number")
    if min_v is not None and dv < Decimal(str(min_v)):
        _bad(k, f"must be >= {min_v}")
    if max_v is not None and dv > Decimal(str(max_v)):
        _bad(k, f"must be <= {max_v}")
    return float(dv)


def req_enum(b, k, choices):
    v = b.get(k)
    if not isinstance(v, str) or v not in choices:
        _bad(k, f"must be one of {list(choices)}")
    return v


def opt_enum(b, k, choices, default=None):
    v = b.get(k)
    if v is None:
        return default
    if not isinstance(v, str) or v not in choices:
        _bad(k, f"must be one of {list(choices)}")
    return v


def req_date(b, k):
    v = b.get(k)
    d = parse_date(v)
    if d is None:
        _bad(k, "required ISO date (YYYY-MM-DD)")
    return d


def opt_date(b, k):
    v = b.get(k)
    if v is None:
        return None
    d = parse_date(v)
    if d is None:
        _bad(k, "must be an ISO date (YYYY-MM-DD)")
    return d
