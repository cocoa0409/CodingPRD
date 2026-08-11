"""Shared list-endpoint helper: created_at ASC ordering + pagination."""

from db import sort_key
from envelope import ok_list
from validators import pagination


def page_out(rows, serializer):
    limit, offset = pagination()
    rows = sorted(rows, key=sort_key)
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)
