"""Shared list helpers for route handlers."""
import db
from middleware import parse_pagination, paginate
from response import success_array


def sorted_by_created(records):
    """Sort records by created_at ascending (PRD §2.3 default list ordering),
    tie-break by the monotonic creation sequence so that records minted at the
    same logical-clock millisecond keep their append order (the random UUID id
    must NOT be the tie-break — it scrambles append order non-deterministically).
    """
    return sorted(records, key=lambda r: (db.parse_iso(r["created_at"]).timestamp(), r.get("_seq", 0)))


def list_response(records, serializer):
    limit, offset = parse_pagination()
    ordered = sorted_by_created(records)
    page, total = paginate(ordered, limit, offset)
    items = [serializer(r) for r in page]
    return success_array(items, limit, offset, total)
