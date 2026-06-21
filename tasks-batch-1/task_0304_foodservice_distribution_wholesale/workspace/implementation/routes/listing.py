"""Shared list-endpoint helper: filter -> sort by created_at ASC -> paginate."""
from flask import request

import middleware
import response


def list_response(records, serializer, filters=None):
    """Filter records by exact-match query params, sort by created_at ASC,
    paginate per PRD §2.3, and emit the array envelope.

    `filters` maps query-param name -> record field name. A param absent from
    the query string is not applied.
    """
    items = list(records)
    if filters:
        for param, field in filters.items():
            val = request.args.get(param)
            if val is not None:
                items = [r for r in items if str(r.get(field)) == val]
    items.sort(key=lambda r: r["created_at"])
    page, limit, offset, total, has_more = middleware.paginate(items)
    data = [serializer(r) for r in page]
    return response.array_response(data, limit, offset, total, has_more)
