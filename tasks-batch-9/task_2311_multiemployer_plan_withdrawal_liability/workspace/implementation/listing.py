"""Shared list-endpoint plumbing: query screening, ordering, pagination."""

from response import arr
from validate import page_params, query_int_filter, query_str


def paged(rows, serializer, key=None):
    """`rows` is already filtered; ordering defaults to created_at ascending."""
    limit, offset = page_params()
    ordered = sorted(rows, key=key or (lambda r: r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return arr([serializer(row) for row in window], limit, offset, total)


def eq_filter(rows, field, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]


def str_filters(rows, spec):
    """spec maps query-parameter name -> row field name."""
    for param, field in spec.items():
        rows = eq_filter(rows, field, query_str(param))
    return rows


def int_filter(rows, param, field):
    value = query_int_filter(param)
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]
