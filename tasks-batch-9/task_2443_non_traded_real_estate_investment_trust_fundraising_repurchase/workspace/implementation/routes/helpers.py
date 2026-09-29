"""Shared route plumbing."""

import serialize
import validate as V
from errors import fail
from response import array_response, created, object_response
from store import get


def resolve(collection, row_id):
    """Levels 4 — a reference that does not resolve is always 404."""
    row = get(collection, row_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return row


def single(row, status=200):
    return object_response(serialize.dump(row), status)


def new(row):
    return created(serialize.dump(row))


def listing(rows, limit, offset):
    page, total = V.paginate(rows, limit, offset)
    return array_response(serialize.dump_all(page), limit, offset, total)


def matches(row, field, value):
    return value is None or row.get(field) == value
