"""Shared route helpers: list scoping and serialization."""

from auth import owns_judgment
from store import public


def serialize(row):
    return public(row)


def scope(ctx, rows, judgment_for):
    if not ctx.entity_backed:
        return rows
    return [r for r in rows if owns_judgment(ctx, judgment_for(r))]


def apply_filter(rows, args, field, param=None):
    value = args.get(param or field)
    if value is None or value == "":
        return rows
    return [r for r in rows if r.get(field) == value]
