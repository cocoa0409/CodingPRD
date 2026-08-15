"""Shared list-endpoint machinery: filtering, created_at-asc sort, pagination."""

from response import success_list
from util import pagination_params
from services.serializers import serialize_many


def _matches(value, raw: str) -> bool:
    if isinstance(value, bool):
        return (raw.strip().lower() in ("true", "1", "yes")) == value
    if value is None:
        return raw.strip().lower() in ("null", "none", "")
    return str(value) == raw


def list_response(collection, filters):
    """filters: query-param names compared against str(resource[field]) with
    boolean normalization."""
    from flask import request

    limit, offset = pagination_params()
    items = list(collection)
    for field in filters:
        raw = request.args.get(field)
        if raw is None:
            continue
        items = [r for r in items if _matches(r.get(field), raw)]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(serialize_many(page), total, limit, offset)
