"""Common request helpers: body parsing, pagination, filter validation."""
from flask import request
from errors import raise_err, ERR_VALIDATION


def get_json_body():
    """Return the parsed JSON body (empty dict if none)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise_err(ERR_VALIDATION, "invalid JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_VALIDATION, "JSON body must be an object")
    return body


def require_field(body, name, expected_type=None):
    if name not in body or body[name] is None:
        raise_err(ERR_VALIDATION, f"missing required field: {name}")
    v = body[name]
    if expected_type is not None and not _isinstance_strict(v, expected_type):
        raise_err(ERR_VALIDATION, f"field {name} has wrong type")
    return v


def _isinstance_strict(v, t):
    # bool is a subclass of int in Python; reject int-typed bools explicitly.
    if t is int:
        return isinstance(v, int) and not isinstance(v, bool)
    if t is bool:
        return isinstance(v, bool)
    if isinstance(t, tuple):
        return any(_isinstance_strict(v, x) for x in t)
    return isinstance(v, t)


def opt_field(body, name, expected_type=None, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if expected_type is not None and not _isinstance_strict(v, expected_type):
        raise_err(ERR_VALIDATION, f"field {name} has wrong type")
    return v


def parse_pagination():
    """Return (limit, offset). Enforces defaults 10/0, min 1, max 100."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise_err(ERR_VALIDATION, "invalid limit/offset")
    if limit < 1 or limit > 100:
        raise_err(ERR_VALIDATION, "limit out of range")
    if offset < 0:
        raise_err(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Slice items and return (page_items, pagination_meta)."""
    total = len(items)
    page = items[offset: offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


def sort_by_created(items):
    """Default list ordering: created_at ASC (fallback on _seq for stability)."""
    return sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))
