"""Shared route helpers."""

from envelope import list_response, object_response, paginate
from store import by_created

__all__ = ["object_response", "paged", "filter_eq"]


def paged(rows, serializer, limit, offset):
    """List endpoints sort by created_at ascending unless stated otherwise."""
    window, total = paginate(by_created(rows), limit, offset)
    return list_response([serializer(row) for row in window], limit, offset, total)


def filter_eq(rows, field, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]
