"""Shared list-endpoint plumbing."""

from db import sorted_rows
from response import paginate


def filtered(collection, filters):
    """filters: iterable of (field_name, value); a None value is not applied."""
    active = [(field, value) for field, value in filters if value is not None]
    rows = []
    for row in collection.values():
        if all(row.get(field) == value for field, value in active):
            rows.append(row)
    return sorted_rows(rows)


def list_rows(collection, serializer, filters):
    return paginate(filtered(collection, filters), serializer)
