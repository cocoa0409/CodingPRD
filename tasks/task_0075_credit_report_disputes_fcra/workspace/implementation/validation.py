from flask import request

from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_PAGINATION_RANGE,
)


def get_body():
    if request.data is None or request.data == b"":
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise err(ERR_VALIDATION, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_VALIDATION, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_VALIDATION, "Missing required field: %s" % f)


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err(ERR_VALIDATION, "Field %s must be a non-empty string" % field)
    return v


def require_enum(body, field, members):
    v = body.get(field)
    if v not in members:
        raise err(ERR_VALIDATION, "Field %s must be one of %s" % (field, sorted(members)))
    return v


def require_int(body, field, min_value=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_VALIDATION, "Field %s must be an integer" % field)
    if min_value is not None and v < min_value:
        raise err(ERR_VALIDATION, "Field %s must be >= %s" % (field, min_value))
    return v


def parse_pagination():
    """Returns (limit, offset). Raises ERR_PAGINATION_RANGE on out-of-range."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_PAGINATION_RANGE, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_PAGINATION_RANGE, "limit must be in [1,100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_PAGINATION_RANGE, "offset must be >= 0")
        if offset < 0:
            raise err(ERR_PAGINATION_RANGE, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items: full sorted list. Returns (page_items, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
