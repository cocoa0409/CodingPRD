"""Shared list-endpoint helper: filter -> sort(created_at asc) -> paginate."""
from validate import pagination
from response import listing


def list_response(collection, serializer, filters=None):
    """Filter, sort by created_at ascending (stable via _seq), paginate.

    `filters` is a dict of field -> expected value; only records whose field
    equals the value are kept. None filter values are ignored.
    """
    limit, offset = pagination()
    items = list(collection.values())
    if filters:
        for field, expected in filters.items():
            if expected is None:
                continue
            items = [r for r in items if r.get(field) == expected]
    # PRD §2.3: sort by created_at ascending. _seq guarantees deterministic
    # tie-break when many rows share the same logical-clock timestamp.
    items.sort(key=lambda r: (r.get("created_at"), r.get("_seq", 0)))
    total = len(items)
    page = items[offset:offset + limit]
    return listing([serializer(r) for r in page], limit, offset, total)
