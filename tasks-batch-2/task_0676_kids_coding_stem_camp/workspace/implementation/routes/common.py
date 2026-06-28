"""Shared route helpers: query-arg access and list pagination."""
from flask import request

from response import list_response
from serialize import out


def arg(name):
    return request.args.get(name)


def paginate(items, limit, offset):
    """Sort by creation order (ascending) and return a paginated list response."""
    items = sorted(items, key=lambda r: r["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return list_response([out(r) for r in page], limit, offset, total)
