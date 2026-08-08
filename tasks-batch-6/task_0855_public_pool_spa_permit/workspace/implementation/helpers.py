"""Small route-level helpers shared by every route module."""

from errors import ApiError
from response import list_response
from store import DB, ordered
from validation import paginate, pagination


def get_or_404(collection, key, error_id):
    if not isinstance(key, str) or key not in collection:
        raise ApiError(error_id, "No such resource: %s" % key)
    return collection[key]


def facility_or_404(facility_id):
    return get_or_404(DB.facilities, facility_id, "ERR_FACILITY_NOT_FOUND")


def paged_list(rows, serializer):
    limit, offset = pagination()
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([serializer(r) for r in page], limit, offset, total)


def matches(value, expected):
    return expected is None or value == expected
