"""Shared helpers for the route modules."""

from db import sort_rows
from response import ok_list, serialize
import validators as v


def paged(rows, filters, order="default"):
    """Pagination bounds (priority 19), then filters, then the collection order."""
    limit, offset = v.pagination()
    rows = v.apply_filters(rows, filters)
    if order == "queue":
        rows = sorted(
            rows, key=lambda r: (-r["priority_score"], r["created_at"], r["_seq"])
        )
    elif order == "rules":
        rows = sorted(
            rows, key=lambda r: (r["evaluation_order"], r["created_at"], r["_seq"])
        )
    else:
        rows = sort_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([serialize(r) for r in page], limit, offset, total)
