from flask import request

from errors import err


def get_body():
    """Parse JSON body; return {} if empty. Raise ERR_INVALID_REQUEST on malformed JSON."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def paginate(items):
    """Apply limit/offset query params. items must already be sorted.
    Returns (window, limit, offset, total_count)."""
    total = len(items)
    limit = _int_param("limit", 10, 1, 100)
    offset = _int_param("offset", 0, 0, None)
    window = items[offset:offset + limit]
    return window, limit, offset, total


def _int_param(name, default, lo, hi):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Invalid %s parameter" % name)
    if lo is not None and val < lo:
        raise err("ERR_INVALID_REQUEST", "%s below minimum" % name)
    if hi is not None and val > hi:
        raise err("ERR_INVALID_REQUEST", "%s above maximum" % name)
    return val


def sort_by_created(rows):
    return sorted(rows, key=lambda r: r.get("_seq", 0))


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def check_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "Invalid value for %s" % field)
