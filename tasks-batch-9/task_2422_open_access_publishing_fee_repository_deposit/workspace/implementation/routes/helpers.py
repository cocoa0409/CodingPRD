"""Shared list helpers."""
from db import sort_rows
from response import list_response
from schemas import serialize_many
from validation import pagination


def paged(rows, fields, sort=True):
    limit, offset = pagination()
    ordered = sort_rows(rows) if sort else list(rows)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return list_response(serialize_many(window, fields), limit, offset, total)
