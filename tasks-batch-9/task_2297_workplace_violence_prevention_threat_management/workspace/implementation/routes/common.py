"""Shared route helpers."""

from db import in_order
from errors import ApiError
from response import list_response, object_response
from serialize import dump
from validation import pagination


def lookup(collection, row_id, error_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id, "No such resource: %s" % row_id)
    return row


def single(row, status=200):
    return object_response(dump(row), status)


def paged(rows, dumper=dump):
    limit, offset = pagination()
    ordered = in_order(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return list_response(
        [dumper(r) for r in page],
        limit,
        offset,
        total,
        offset + len(page) < total,
    )


def matches(row, filters):
    for field, expected in filters.items():
        if expected is None:
            continue
        if row.get(field) != expected:
            return False
    return True


def filtered(rows, filters):
    return [r for r in rows if matches(r, filters)]
