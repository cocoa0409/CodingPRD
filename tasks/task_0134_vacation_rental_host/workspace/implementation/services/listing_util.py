"""List endpoint helpers: created_at-ascending sort + offset pagination (PRD §2.3)."""
from models import serialize


def sort_and_paginate(items, limit, offset):
    """Sort by created_at ascending (oldest first), then apply offset/limit.
    Ties broken by the monotonic insertion sequence so order is deterministic."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(e) for e in page], total
