"""Shared list-endpoint plumbing."""
from flask import request

import db
import response


def match_filters(records, specs):
    """specs: iterable of (query_param, record_key). Filters combine conjunctively."""
    out = list(records)
    for param, key in specs:
        raw = request.args.get(param)
        if raw is None:
            continue
        out = [r for r in out if _as_text(r.get(key)) == raw]
    return out


def _as_text(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def list_collection(collection, specs, serializer):
    rows = match_filters(db.ordered(collection), specs)
    page, limit, offset, total = response.paginate(rows)
    return response.list_response([serializer(r) for r in page], limit, offset, total)
