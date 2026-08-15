"""Shared route helpers: pagination, filtering, list envelope (PRD 2.3)."""
from flask import request

from errors import raise_error, ERR_INVALID_REQUEST
from response import success_list


def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def list_response(records, filters, serializer):
    """Exact-match filters (None skipped), creation-order ascending, then paginate."""
    items = list(records)
    for field, value in filters:
        if value is None:
            continue
        items = [r for r in items if r.get(field) == value]
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)
