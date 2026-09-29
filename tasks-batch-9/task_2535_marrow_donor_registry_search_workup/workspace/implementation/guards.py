"""Small shared rungs: existence lookups and list rendering.

Pagination is rung 4 and path-id resolution is rung 5, so every list route reads
its pagination window *before* it resolves any path identifier.
"""

from flask import request

from envelope import paginated
from errors import ApiError
from store import ordered


def find(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def render_list(rows, serializer, limit, offset, sort_key=None):
    if sort_key is None:
        rows = ordered(rows)
    else:
        rows = sorted(rows, key=sort_key)
    return paginated([serializer(row) for row in rows], limit, offset)


def arg(name):
    return request.args.get(name)
