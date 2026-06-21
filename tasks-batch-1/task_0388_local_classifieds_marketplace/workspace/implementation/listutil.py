"""List endpoint helper: sort by created_at ascending (oldest first, §2.3),
apply the page window, and serialize."""
from response import array_response


def sort_key(rec):
    # Sort by created_at ascending; tie-break by monotonic creation sequence so
    # records sharing a logical-clock instant still order oldest-first (§2.3).
    return (rec["created_at"], rec.get("_seq", 0))


def paginate_and_respond(records, limit, offset, serialize):
    ordered = sorted(records, key=sort_key)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    items = [serialize(r) for r in window]
    return array_response(items, limit, offset, total)
