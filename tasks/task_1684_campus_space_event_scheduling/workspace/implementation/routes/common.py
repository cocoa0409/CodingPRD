"""Shared helpers for the route modules."""

import response
from errors import ApiError


def apply_filters(rows, args, mapping):
    """A filter whose value matches no row returns an empty page; list filters
    never raise."""
    out = rows
    for param, getter in mapping.items():
        if param not in args:
            continue
        raw = args.get(param)
        out = [r for r in out if _stringify(getter(r)) == raw]
    return out


def _stringify(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def list_response(rows, args, serializer, mapping=None):
    if mapping:
        rows = apply_filters(rows, args, mapping)
    window, limit, offset, total = response.paginate(rows, args)
    return response.array_response([serializer(r) for r in window], limit, offset, total)


def one(data, status=200):
    return response.object_response(data, status)


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)
