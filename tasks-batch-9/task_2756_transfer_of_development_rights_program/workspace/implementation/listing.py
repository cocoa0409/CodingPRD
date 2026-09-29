"""Shared list-endpoint helper (PRD 2.3)."""

from core import respond_list, sort_rows
from validators import pagination


def paged(rows, serializer):
    limit, offset = pagination()
    ordered = sort_rows(rows)
    total_count = len(ordered)
    window = ordered[offset:offset + limit]
    return respond_list([serializer(r) for r in window], limit, offset, total_count)


def match(rows, **filters):
    result = []
    for row in rows:
        keep = True
        for key, expected in filters.items():
            if expected is None:
                continue
            if row.get(key) != expected:
                keep = False
                break
        if keep:
            result.append(row)
    return result
