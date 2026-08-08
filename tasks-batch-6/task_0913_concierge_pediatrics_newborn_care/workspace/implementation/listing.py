"""Shared list-endpoint plumbing: sort by created_at ASC, then paginate."""
from envelope import array_response
from store import by_seq


def paginated(rows, serializer, limit, offset):
    ordered = by_seq(rows)
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return array_response([serializer(row) for row in page], limit, offset, total)
