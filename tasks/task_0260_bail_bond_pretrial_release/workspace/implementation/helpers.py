"""Shared helpers: field validation, list pagination/sorting, FK existence."""
from errors import err


def require_fields(body, names):
    """ERR_INVALID_REQUEST if any required field is absent or None."""
    for name in names:
        if name not in body or body[name] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)


def require_int(body, name, *, required=True, min_value=None, max_value=None,
                gt=None, default=None):
    """Validate / coerce an integer field. Returns the value (or default).

    bool is rejected (it is an int subclass but not a valid integer field here).
    """
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % name)
    if gt is not None and not val > gt:
        raise err("ERR_INVALID_REQUEST", "Field %s must be > %s." % (name, gt))
    if min_value is not None and val < min_value:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (name, min_value))
    if max_value is not None and val > max_value:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s." % (name, max_value))
    return val


def require_str(body, name, *, required=True, default=None, nonempty=True):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    val = body[name]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string." % name)
    if nonempty and val.strip() == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must not be empty." % name)
    return val


def require_enum(body, name, allowed, *, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    val = body[name]
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s." % (name, sorted(allowed)))
    return val


def require_bool(body, name, *, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % name)
    return val


def paginate(records, limit, offset, *, sort_key="created_at"):
    """Sort ascending by sort_key (default created_at) then slice.

    Returns (page_items, total_count). Stable secondary sort on id keeps
    same-timestamp records deterministic and in insertion-ish order.
    """
    ordered = sorted(records, key=lambda r: (r.get(sort_key), r.get("id")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
