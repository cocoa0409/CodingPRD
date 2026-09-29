"""Shared helpers for the route modules."""

from flask import request

from db import creation_key, serialize_many
from envelope import list_response


def filtered(rows, mapping):
    """Apply optional equality filters supplied as query parameters."""
    for param, field in mapping.items():
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return rows


def respond_list(rows, limit, offset, key=None):
    rows = sorted(rows, key=key or creation_key)
    total_count = len(rows)
    page = rows[offset:offset + limit]
    return list_response(serialize_many(page), limit, offset, total_count)
