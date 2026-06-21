"""Shared list helper: filter, sort by created_at asc (PRD §2.3), paginate."""

from response import array_response


def sorted_collection(collection):
    """All records sorted by created_at ascending, ties broken by insertion
    sequence so ordering is stable even within the same millisecond."""
    return sorted(collection.values(),
                  key=lambda r: (r["created_at"], r.get("_seq", 0)))


def paginate_and_respond(records, limit, offset, serializer):
    total = len(records)
    page = records[offset:offset + limit]
    items = [serializer(r) for r in page]
    return array_response(items, limit, offset, total)
