"""Request shape validation helpers (priority 4). All raise ERR_INVALID_REQUEST."""
from flask import request
from errors import bad
from util import is_num, to_dec, parse_dt, parse_date, HHMM_RE


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object")
    return data


def _present(b, k):
    return k in b and b[k] is not None


def req_str(b, k):
    if not _present(b, k) or not isinstance(b[k], str):
        bad(f"Field '{k}' is required and must be a string")
    return b[k]


def opt_str(b, k, default=None):
    if not _present(b, k):
        return default
    if not isinstance(b[k], str):
        bad(f"Field '{k}' must be a string")
    return b[k]


def _int_value(v, k):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad(f"Field '{k}' must be an integer")
    if isinstance(v, float):
        if not v.is_integer():
            bad(f"Field '{k}' must be an integer")
        v = int(v)
    return v


def req_int(b, k, mn=None, mx=None):
    if not _present(b, k):
        bad(f"Field '{k}' is required")
    v = _int_value(b[k], k)
    if mn is not None and v < mn:
        bad(f"Field '{k}' is below minimum {mn}")
    if mx is not None and v > mx:
        bad(f"Field '{k}' exceeds maximum {mx}")
    return v


def opt_int(b, k, default=None, mn=None, mx=None):
    if not _present(b, k):
        return default
    return req_int(b, k, mn=mn, mx=mx)


def _num_range(v, k, mn, mx, gt):
    if mn is not None and v < mn:
        bad(f"Field '{k}' is below minimum {mn}")
    if mx is not None and v > mx:
        bad(f"Field '{k}' exceeds maximum {mx}")
    if gt is not None and not (v > gt):
        bad(f"Field '{k}' must be greater than {gt}")


def req_num(b, k, mn=None, mx=None, gt=None):
    """Returns Decimal."""
    if not _present(b, k):
        bad(f"Field '{k}' is required")
    if not is_num(b[k]):
        bad(f"Field '{k}' must be a number")
    v = to_dec(b[k])
    _num_range(v, k, mn, mx, gt)
    return v


def opt_num(b, k, default=None, mn=None, mx=None, gt=None):
    if not _present(b, k):
        return default
    return req_num(b, k, mn=mn, mx=mx, gt=gt)


def opt_bool(b, k, default=None):
    if not _present(b, k):
        return default
    if not isinstance(b[k], bool):
        bad(f"Field '{k}' must be a boolean")
    return b[k]


def req_enum(b, k, allowed):
    v = req_str(b, k)
    if v not in allowed:
        bad(f"Field '{k}' must be one of {sorted(allowed)}")
    return v


def opt_enum(b, k, allowed, default=None):
    if not _present(b, k):
        return default
    return req_enum(b, k, allowed)


def req_dt(b, k):
    v = req_str(b, k)
    dt = parse_dt(v)
    if dt is None:
        bad(f"Field '{k}' must be an ISO 8601 datetime")
    return dt


def opt_dt(b, k, default=None):
    if not _present(b, k):
        return default
    return req_dt(b, k)


def req_date(b, k):
    v = req_str(b, k)
    d = parse_date(v)
    if d is None:
        bad(f"Field '{k}' must be a YYYY-MM-DD date")
    return d


def opt_date(b, k, default=None):
    if not _present(b, k):
        return default
    return req_date(b, k)


def req_hhmm(b, k):
    v = req_str(b, k)
    if not HHMM_RE.match(v):
        bad(f"Field '{k}' must be HH:MM 24h")
    return v


def opt_hhmm(b, k, default=None):
    if not _present(b, k):
        return default
    return req_hhmm(b, k)


def req_list(b, k):
    if not _present(b, k):
        bad(f"Field '{k}' is required")
    if not isinstance(b[k], list):
        bad(f"Field '{k}' must be an array")
    return b[k]


def opt_list(b, k):
    if not _present(b, k):
        return []
    if not isinstance(b[k], list):
        bad(f"Field '{k}' must be an array")
    return b[k]


def pagination_params():
    """limit (default 10, 1..100), offset (default 0, >=0)."""
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)

    def _pint(raw, k):
        if not raw.isdigit():
            bad(f"Query parameter '{k}' must be a non-negative integer")
        return int(raw)

    if raw_limit is None:
        limit = 10
    else:
        limit = _pint(raw_limit, "limit")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        offset = _pint(raw_offset, "offset")
    return limit, offset
