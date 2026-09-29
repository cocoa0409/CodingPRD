"""Shared list-filtering helpers for the read endpoints."""

import store
from envelope import list_response
from validators import paginate, pagination


def filter_equals(rows, request, spec):
    """spec: iterable of (query_param, row_field) string-equality filters."""
    out = rows
    for param, field in spec:
        value = request.args.get(param)
        if value is None or value == "":
            continue
        out = [r for r in out if r.get(field) == value]
    return out


def filter_bool(rows, request, param, field):
    value = request.args.get(param)
    if value is None or value == "":
        return rows
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        wanted = True
    elif lowered in ("false", "0"):
        wanted = False
    else:
        return rows
    return [r for r in rows if bool(r.get(field)) is wanted]


def collection_response(rows, request, serializer):
    limit, offset = pagination(request)
    rows = store.ordered(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([serializer(r) for r in page], limit, offset, total)
