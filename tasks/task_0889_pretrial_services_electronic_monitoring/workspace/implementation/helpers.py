"""Shared route-level helpers."""

from errors import ApiError
from response import list_response
from store import ordered
from validation import pagination, paginate, qs


def get_or_404(collection, key):
    if not isinstance(key, str) or key not in collection:
        raise ApiError("ERR_NOT_FOUND", "No such resource: %s" % key)
    return collection[key]


def paged_list(rows, serializer):
    limit, offset = pagination()
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([serializer(r) for r in page], limit, offset, total)


def matches(value, expected):
    return expected is None or value == expected


def matches_int(value, expected_raw):
    if expected_raw is None:
        return True
    try:
        return value == int(expected_raw)
    except (TypeError, ValueError):
        return False
