"""Shared route helpers."""

from errors import ApiError
from store import sorted_rows
from validate import pagination, paginate


def ensure_unique_code(table, field, value):
    """Rung 930 — globally unique business codes."""
    for row in table.values():
        if row[field] == value:
            raise ApiError("ERR_DUPLICATE_CODE")


def listing(rows, serializer, filters=None):
    """Apply equality filters, canonical ordering and pagination."""
    limit, offset = pagination()
    if filters:
        for field, wanted in filters.items():
            if wanted is None:
                continue
            rows = [row for row in rows if row.get(field) == wanted]
    ordered = sorted_rows(rows)
    page, total = paginate(ordered, limit, offset)
    return [serializer(row) for row in page], limit, offset, total
