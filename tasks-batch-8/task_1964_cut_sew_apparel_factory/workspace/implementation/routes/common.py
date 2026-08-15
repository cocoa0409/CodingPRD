"""Shared list-endpoint helper (PRD §2.3)."""

from flask import request

from response import parse_pagination, success_list
from services.core import public, sorted_records


def list_response(records, filters):
    """filters: list of callables(rec) -> bool; all must pass. Results are
    sorted created_at ascending and paginated with limit/offset."""
    items = [r for r in sorted_records(records) if all(f(r) for f in filters)]
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, len(items))


def eq_filter(field, value):
    if value is None:
        return None
    return lambda r: r.get(field) == value


def active_filters(pairs):
    """pairs: [(field, query_value), ...] — None values dropped."""
    return [f for f in (eq_filter(k, v) for k, v in pairs) if f is not None]
