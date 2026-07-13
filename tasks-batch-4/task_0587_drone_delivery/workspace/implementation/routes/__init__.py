"""Route blueprints."""
from db import sorted_rows
from response import listing
from validation import paginate, pagination


def list_response(rows, serializer, limit, offset):
    ordered = sorted_rows(rows)
    page, total = paginate(ordered, limit, offset)
    return listing([serializer(r) for r in page], limit, offset, total)


def filtered(rows, **filters):
    out = []
    for row in rows:
        if all(value is None or row.get(key) == value for key, value in filters.items()):
            out.append(row)
    return out


__all__ = ["list_response", "filtered", "pagination"]
