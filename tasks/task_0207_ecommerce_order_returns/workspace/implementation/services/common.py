"""Shared helpers: pagination, body parsing, field validation, lookups."""
from flask import request

from errors import err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_VALIDATION

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0


def parse_body():
    """Return the JSON body as a dict, or raise ERR_INVALID_REQUEST."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Request body must be valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def get_pagination():
    """Parse limit/offset query params with defaults & bounds (PRD §2.3).

    Out-of-range or malformed values are reported as ERR_VALIDATION (422).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION, "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise err(ERR_VALIDATION, "limit out of range")

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION, "offset must be an integer")
        if offset < PAGINATION_MIN_OFFSET:
            raise err(ERR_VALIDATION, "offset out of range")

    return limit, offset


def paginate(rows, serializer):
    """Sort by created_at asc (stable, tie-broken by insertion _seq), apply
    limit/offset, serialize, and return (data_list, pagination_meta)."""
    limit, offset = get_pagination()
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    data = [serializer(r) for r in page]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return data, meta


# ---- field validation helpers ----

def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % n)


def require_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name)
    return v


def require_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    return v


def optional_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    return v


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean" % name)
    return v


def require_enum(body, name, members):
    v = body.get(name)
    if not isinstance(v, str) or v not in members:
        raise err(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (name, sorted(members)))
    return v


def lookup(collection, _id):
    """Existence check -> ERR_NOT_FOUND (404) if missing."""
    rec = collection.get(_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found: %s" % _id)
    return rec
