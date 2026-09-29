"""Shared route helpers."""

from db import creation_order
from errors import fail
from middleware import authenticate, authorize
from response import arr
from validation import pagination


def auth(*allowed):
    """Groups 1 and 2 of the validation precedence."""
    user_id, role = authenticate()
    authorize(role, allowed)
    return user_id, role


def need(store, key, error_id):
    record = store.get(key)
    if record is None:
        fail(error_id, "Resource '%s' was not found" % key)
    return record


def listing(records, serializer):
    limit, offset = pagination()
    ordered = creation_order(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return arr([serializer(r) for r in page], limit, offset, total)
