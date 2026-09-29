"""Shared route helpers: paging and uniqueness."""

from db import paginate, sorted_records
from errors import fail
from response import ok_list


def page(rows, limit, offset):
    """Default ordering is created_at ascending (PRD 2.3)."""
    ordered = sorted_records(None, rows)
    rows_page, total, has_more = paginate(ordered, limit, offset)
    return ok_list(rows_page, limit, offset, total, has_more)


def unique(collection, field, value, label):
    """Rung 8 — ERR_DUPLICATE_IDENTIFIER on the four create operations."""
    for record in collection.values():
        if record.get(field) == value:
            fail("ERR_DUPLICATE_IDENTIFIER",
                 "%s '%s' is already registered" % (label, value))


def matches(record, filters):
    for field, wanted in filters.items():
        if wanted is not None and record.get(field) != wanted:
            return False
    return True
