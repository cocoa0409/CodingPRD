"""Request-shape validators (PRD section 2.8 layer 3) and pagination parsing."""
from flask import request

import util
from errors import ERR_VALIDATION, raise_err


def _bad(field, why="invalid or missing"):
    raise_err(ERR_VALIDATION, "field '%s': %s" % (field, why))


def body():
    """JSON object body; an absent body is treated as {} so required-field checks fire."""
    j = request.get_json(silent=True)
    if j is None:
        return {}
    if not isinstance(j, dict):
        raise_err(ERR_VALIDATION, "request body must be a JSON object")
    return j


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or v == "":
        _bad(name, "must be a non-empty string")
    return v


def opt_str(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, str):
        _bad(name, "must be a string")
    return v


def req_int(b, name, min=None, max=None):
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name, "must be an integer")
    if min is not None and v < min:
        _bad(name, "must be >= %s" % min)
    if max is not None and v > max:
        _bad(name, "must be <= %s" % max)
    return v


def opt_int(b, name, default=None, min=None, max=None):
    v = b.get(name)
    if v is None:
        return default
    return req_int(b, name, min=min, max=max)


def req_num(b, name, gt=None, gte=None, lte=None):
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(name, "must be a number")
    d = util.dec(v)
    if gt is not None and not d > util.dec(gt):
        _bad(name, "must be > %s" % gt)
    if gte is not None and not d >= util.dec(gte):
        _bad(name, "must be >= %s" % gte)
    if lte is not None and not d <= util.dec(lte):
        _bad(name, "must be <= %s" % lte)
    return d


def opt_num(b, name, default=None, gt=None, gte=None, lte=None):
    v = b.get(name)
    if v is None:
        return default
    return req_num(b, name, gt=gt, gte=gte, lte=lte)


def req_bool(b, name):
    v = b.get(name)
    if not isinstance(v, bool):
        _bad(name, "must be a boolean")
    return v


def opt_bool(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    return req_bool(b, name)


def req_enum(b, name, allowed):
    v = b.get(name)
    if not isinstance(v, str) or v not in allowed:
        _bad(name, "must be one of %s" % sorted(allowed))
    return v


def req_dt(b, name):
    return util.parse_dt(b.get(name), field=name)


def opt_dt(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    return util.parse_dt(v, field=name)


def present(b, name):
    """True when the key is supplied with a non-null value."""
    return b.get(name) is not None


def pagination():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise_err(ERR_VALIDATION, "limit must be an integer")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise_err(ERR_VALIDATION, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset < 0:
        raise_err(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
