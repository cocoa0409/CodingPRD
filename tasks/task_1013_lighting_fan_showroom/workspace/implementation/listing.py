"""Generic list endpoint helper: equality filters + created_at (seq) sort + pagination."""
from flask import request

from envelope import ok_list
from validation import parse_pagination


def list_response(records, serializer, filters=None):
    """records: iterable of stored dicts.
    filters: {query_param_name: record_key} equality filters.
    """
    items = list(records)
    if filters:
        for param, key in filters.items():
            val = request.args.get(param)
            if val is not None:
                items = [r for r in items if str(r.get(key)) == val]
    items.sort(key=lambda r: r["_seq"])
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)
