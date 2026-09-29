"""Shared list-endpoint plumbing: filters, ordering, pagination (PRD 2.3)."""

from envelope import ok_list
from guards import filter_value, pagination, slice_page
from store import ordered, serialize


def _match(actual, wanted):
    if actual is None:
        return False
    if isinstance(actual, bool):
        return str(actual).lower() == wanted.lower()
    if isinstance(actual, int):
        try:
            return actual == int(wanted)
        except (TypeError, ValueError):
            return False
    return str(actual) == wanted


def apply_filters(rows, spec):
    out = rows
    for param, field in spec:
        wanted = filter_value(param)
        if wanted is not None:
            out = [row for row in out if _match(row.get(field), wanted)]
    return out


def list_response(rows, spec=()):
    limit, offset = pagination()
    matching = ordered(apply_filters(list(rows), spec))
    page = slice_page(matching, limit, offset)
    return ok_list([serialize(row) for row in page], limit, offset, len(matching))
