"""Existence + request-body well-formedness helpers (PRD 2.9)."""
import db
from errors import ApiError


def get_or_404(store, rid):
    ent = store.get(rid)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND")
    return ent


def _present(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_INVALID_REQUEST")
    return body[name]


def as_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST")
    return value


def req_int(body, name, positive=False, nonneg=False, lo=None, hi=None):
    v = as_int(_present(body, name))
    if positive and v <= 0:
        raise ApiError("ERR_INVALID_REQUEST")
    if nonneg and v < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    if lo is not None and v < lo:
        raise ApiError("ERR_INVALID_REQUEST")
    if hi is not None and v > hi:
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def req_str(body, name):
    v = _present(body, name)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def req_enum(body, name, allowed):
    v = _present(body, name)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def req_date(body, name):
    v = _present(body, name)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST")
    try:
        return db.parse_iso(v)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST")


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def require_after(start_dt, end_dt):
    """end must be strictly after start (PRD 2.9)."""
    if not (end_dt > start_dt):
        raise ApiError("ERR_INVALID_REQUEST")
