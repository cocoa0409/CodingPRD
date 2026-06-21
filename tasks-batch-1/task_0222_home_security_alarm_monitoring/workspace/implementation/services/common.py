"""Shared list/pagination and lookup helpers."""
from flask import request

from errors import err, ERR_VALIDATION, ERR_NOT_FOUND

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    """Parse limit/offset query params. Bad values -> ERR_VALIDATION (422)."""
    args = request.args
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION, "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err(ERR_VALIDATION, "limit must be between %d and %d" % (MIN_LIMIT, MAX_LIMIT))
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise err(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def sort_by_created(items):
    """Sort by created_at ascending; stable tie-break by insertion sequence."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def paginate(items, limit, offset):
    total = len(items)
    window = items[offset:offset + limit]
    return window, total


def lookup(store_dict, resource_id):
    """Return the entity or raise ERR_NOT_FOUND (path-referenced existence)."""
    ent = store_dict.get(resource_id)
    if ent is None:
        raise err(ERR_NOT_FOUND, "Resource not found: %s" % resource_id)
    return ent
