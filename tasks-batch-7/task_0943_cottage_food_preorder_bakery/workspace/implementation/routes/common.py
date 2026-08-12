"""Shared list-endpoint helper.  Results are ordered by created_at ascending
(PRD 2.3) with the monotonic id as the deterministic tie-break."""

from db import DB
from response import listing, paginate
from serialize import dump_all


def list_endpoint(ctx, collection, filters, predicate=None):
    limit, offset = ctx.p["_page"]
    records = DB.values(collection)
    if predicate is not None:
        records = [r for r in records if predicate(r)]
    for param, field in filters.items():
        raw = ctx.args.get(param)
        if raw is None or raw == "":
            continue
        records = [r for r in records if _match(r.get(field), raw)]
    page, total = paginate(records, limit, offset)
    return listing(dump_all(collection, page), total, limit, offset)


def _match(value, raw):
    """Query filters never error: an unmatched value simply matches nothing."""
    if value is None:
        return False
    if isinstance(value, bool):
        return str(value).lower() == str(raw).lower()
    return str(value) == str(raw)
