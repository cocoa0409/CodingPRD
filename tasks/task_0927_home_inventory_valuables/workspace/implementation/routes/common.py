"""Shared helpers for the route modules."""

import envelope
import store
from errors import ApiError


def _matches(value, raw):
    if isinstance(value, bool):
        low = raw.lower()
        if low not in ("true", "false"):
            return False
        return (low == "true") == value
    return value == raw


def apply_filters(rows, args, mapping):
    """PRD 2.3: a filter whose value simply matches no row returns an empty
    page; list filters never raise ERR_INVALID_ENUM or ERR_INVALID_REQUEST."""
    out = rows
    for param, getter in mapping.items():
        if param not in args:
            continue
        raw = args.get(param)
        out = [r for r in out if _matches(getter(r), raw)]
    return out


def list_response(rows, args, serializer, mapping=None):
    if mapping:
        rows = apply_filters(rows, args, mapping)
    window, limit, offset, total = envelope.paginate(rows, args)
    return envelope.array_response([serializer(r) for r in window], limit, offset, total)


def one(data, status=200):
    return envelope.object_response(data, status)


def field(name):
    return lambda row: row.get(name)


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def item_of(row_with_item):
    return store.items.get(row_with_item["item_id"])


def household_of_item(item):
    return item.get("household_id") if item else None
