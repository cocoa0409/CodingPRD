"""Shared list-endpoint helper: exact-match filters, created_at-ascending
sort (insertion sequence tie-break), limit/offset pagination (PRD 2.3)."""
from flask import request

from response import ok_list
from util import pagination_params


def list_response(collection, serializer, filters):
    items = list(collection.values())
    for field in filters:
        value = request.args.get(field)
        if value is not None:
            items = [i for i in items if i.get(field) is not None and str(i.get(field)) == value]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = pagination_params()
    page = items[offset : offset + limit]
    return ok_list([serializer(i) for i in page], limit, offset, total)
