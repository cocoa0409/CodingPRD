"""List sorting + pagination helper (PRD §2.3).

Lists are returned in ascending order of created_at (oldest first). Ties broken
by internal creation sequence for determinism.
"""
from models import serialize


def paginate(records, limit, offset, serializer=serialize):
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serializer(r) for r in page], total
