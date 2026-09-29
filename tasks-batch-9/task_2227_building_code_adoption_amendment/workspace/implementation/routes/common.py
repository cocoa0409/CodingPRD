"""Shared list/read plumbing for the route modules."""
from flask import request

import db
import response
import validate


def paged(rows, serializer, limit=None, offset=None):
    if limit is None or offset is None:
        limit, offset = validate.pagination()
    rows = db.ordered(rows)
    total = len(rows)
    page = rows[offset:offset + limit]
    return response.list_response([serializer(row) for row in page], limit, offset, total)


def apply_filters(rows, spec):
    """spec: {query_param: (record_key, caster)} — equality filters only."""
    for param, (key, caster) in spec.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        try:
            value = caster(raw)
        except (TypeError, ValueError):
            return []
        rows = [row for row in rows if row.get(key) == value]
    return rows


def as_str(value):
    return value


def as_int(value):
    return int(value.strip())
