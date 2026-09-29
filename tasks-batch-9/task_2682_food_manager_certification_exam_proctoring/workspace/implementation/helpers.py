"""Shared list/pagination and scope-filter helpers."""
from authz import deny_scope
from envelope import ok_list, pagination, window
from store import store


def paged(rows):
    """Validates pagination (priority 5) then windows created_at ascending."""
    limit, offset = pagination()
    ordered = store.ordered(rows)
    page, total = window(ordered, limit, offset)
    return ok_list(page, limit, offset, total)


def scoped_filter(explicit, own):
    """An entity-backed caller may only name its own scope in a filter."""
    if explicit is not None and explicit != own:
        deny_scope("filter names a scope outside the caller's own")
    return own


def match(row, field, value):
    return value is None or row[field] == value
