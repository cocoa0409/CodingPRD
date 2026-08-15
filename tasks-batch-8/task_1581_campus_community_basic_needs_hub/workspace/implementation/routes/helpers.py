"""Shared route helpers: serialization, list pagination, scoped listing."""
from flask import request

from response import success_list
from services.core import public, sorted_records
from validate import get_pagination


def list_response(collection, filters=None, serializer=public, scope_fn=None,
                  membership_filter_field=None):
    """List with created_at-ascending sort, query filters, caller scoping, pagination.

    filters: {field: raw query value}; equality match on the serialized record.
    membership_filter_field: field whose serialized value is a list — query value
    matches by membership rather than equality.
    scope_fn: optional callable narrowing serialized records for the caller.
    """
    items = [serializer(r) for r in sorted_records(collection)]
    if scope_fn is not None:
        items = [i for i in items if scope_fn(i)]
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            if field == membership_filter_field:
                items = [i for i in items if value in (i.get(field) or [])]
            else:
                items = [i for i in items if i.get(field) is not None and str(i.get(field)) == value]
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list(page, total, limit, offset)
