"""Shared route helpers: existence lookups and paginated list responses."""

from db import by_creation
from errors import fail
from response import ok_list
from validate import paging, window


def need(collection, entity_id, error_id, label="record"):
    row = collection.get(entity_id)
    if row is None:
        fail(error_id, "%s %s does not exist" % (label, entity_id))
    return row


def list_response(rows, serializer):
    limit, offset = paging()
    ordered = by_creation(rows)
    page, total = window(ordered, limit, offset)
    return ok_list([serializer(row) for row in page], limit, offset, total)


def match(row, field, value):
    if value is None:
        return True
    return row.get(field) == value
