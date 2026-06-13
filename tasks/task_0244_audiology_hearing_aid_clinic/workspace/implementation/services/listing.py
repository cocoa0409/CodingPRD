"""Shared list-endpoint helper: filter, sort by created_at asc (stable), and
paginate, returning the serialized page plus metadata for the array envelope.
"""

from middleware import parse_pagination, paginate


def sorted_by_created(items):
    """Stable sort by created_at ascending. Python's sort is stable, so equal
    created_at values keep insertion order (the order rows were created)."""
    return sorted(items, key=lambda o: o["created_at"])


def list_page(args, items, serializer):
    """Given query args and an already-filtered list of entity dicts, validate
    pagination, sort by created_at asc, slice, and serialize.

    Returns (serialized_items, limit, offset, total_count).
    """
    limit, offset = parse_pagination(args)
    ordered = sorted_by_created(items)
    page, total = paginate(ordered, limit, offset)
    return [serializer(o) for o in page], limit, offset, total
