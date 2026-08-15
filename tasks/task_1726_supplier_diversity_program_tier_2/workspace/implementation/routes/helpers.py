"""Shared route helpers: pagination and filtered list responses."""
from flask import request

from errors import raise_error, ERR_INVALID_REQUEST
from response import success_list
from services.core import sort_key


def get_pagination():
    """PRD 2.3: limit default 10 (min 1, max 100), offset default 0."""
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
    """created_at ascending (write order on ties), filters, pagination envelope."""
    items = list(records)
    for field, value in (filters or {}).items():
        if value is None:
            continue
        items = [r for r in items if str(r.get(field)) == str(value)]
    items.sort(key=sort_key)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)
