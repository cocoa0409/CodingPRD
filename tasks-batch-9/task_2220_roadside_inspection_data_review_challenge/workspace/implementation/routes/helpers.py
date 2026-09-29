"""Shared route plumbing: listing, filtering and entity views."""

from db import serialize, sorted_rows
from response import ok_list, paginate
from services import cascade


def rows_of(collection):
    return sorted_rows(list(collection.values()))


def filtered(rows, filters):
    out = rows
    for key, value in filters:
        if value is not None:
            out = [r for r in out if r.get(key) == value]
    return out


def listing(rows, limit, offset, view=serialize):
    window, total = paginate(rows, limit, offset)
    return ok_list([view(row) for row in window], limit, offset, total)


def view_violation(violation):
    return serialize(violation, {
        "has_stale_code_pin": cascade.has_stale_code_pin(violation),
    })
