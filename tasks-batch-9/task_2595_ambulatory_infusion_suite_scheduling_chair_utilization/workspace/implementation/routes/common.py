"""Shared route helpers."""

from response import ok_list
from services import present
from validators import pagination


def paged(collection, items):
    limit, offset = pagination()
    total = len(items)
    window = items[offset: offset + limit]
    return ok_list(present.many(collection, window), limit, offset, total)


def by_created(items):
    return sorted(items, key=lambda r: r["_seq"])
