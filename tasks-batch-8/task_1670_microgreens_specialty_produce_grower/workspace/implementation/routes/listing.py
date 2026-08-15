"""Shared list-endpoint helper: filter, sort by created_at ASC, paginate."""
from middleware import parse_pagination
from response import success, serialize


def list_response(records):
    limit, offset = parse_pagination()
    records = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(records)
    page = records[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return success(
        [serialize(r) for r in page], "array", 200, pagination=pagination
    )
