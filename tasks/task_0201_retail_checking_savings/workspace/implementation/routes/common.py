"""Shared list/serialization helpers for route blueprints."""
from middleware import get_pagination, paginate
from response import list_response
from models import public


def sorted_by_created(rows):
    """PRD §2.3: list results sorted by created_at ascending (oldest first).

    Ties (same frozen clock instant) are broken by insertion sequence so order
    is stable and deterministic.
    """
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def paged_list(rows, serializer=None):
    """Sort by created_at, paginate, and return a list_response.

    serializer: optional fn(row) -> dict applied per row (e.g. to attach
    computed fields). Defaults to `public` (strip private bookkeeping fields).
    """
    limit, offset = get_pagination()
    ordered = sorted_by_created(rows)
    page, total = paginate(ordered, limit, offset)
    if serializer is None:
        serializer = public
    items = [serializer(r) for r in page]
    return list_response(items, limit, offset, total)
