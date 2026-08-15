"""List-endpoint helpers: filtering, sorting, pagination (PRD §2.3)."""
from flask import request

from errors import bad_request
from response import success


def _parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad_request("limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad_request("offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def list_response(records, serializer, filters=None):
    """filters: list of (query_param, record_key) exact-match filters."""
    items = list(records)
    if filters:
        for param, key in filters:
            raw = request.args.get(param)
            if raw is not None:
                items = [r for r in items if _matches(r.get(key), raw)]
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    limit, offset = _parse_pagination()
    page = items[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return success([serializer(r) for r in page], status=200, response_type="array", pagination=pagination)


def _matches(value, raw):
    if value is None:
        return raw in ("null", "")
    if isinstance(value, bool):
        return raw.lower() == ("true" if value else "false")
    return str(value) == raw
