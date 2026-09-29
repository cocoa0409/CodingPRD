"""Shared list plumbing for the route modules."""

from envelope import list_response, paginate
from store import ordered
from validators import pagination


def listing(rows, serializer, sort_key=None):
    """Paginate and serialise an already-filtered row set."""
    limit, offset = pagination()
    if sort_key is None:
        items = ordered(rows)
    else:
        items = sorted(rows, key=sort_key)
    window, total = paginate(items, limit, offset)
    return list_response([serializer(row) for row in window], limit, offset, total)


def keep(rows, field, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]
