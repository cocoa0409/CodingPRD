"""Shared route helpers: path resolution and list rendering."""

from errors import ApiError
from envelope import ok_list, paginate, read_pagination
from serializers import dump_many
from store import db, sort_key_created


def resolve(collection, row_id, error_id):
    """Path identifiers are resolved left to right; the first miss decides."""
    row = getattr(db, collection).get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def render_list(kind, rows, sort_key=sort_key_created):
    limit, offset = read_pagination()
    ordered = sorted(rows, key=sort_key)
    total_count = len(ordered)
    page = paginate(ordered, limit, offset)
    return ok_list(dump_many(kind, page), limit, offset, total_count)


def filter_equals(rows, field, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]


def filter_int_equals(rows, field, raw):
    if raw is None or raw == "":
        return rows
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return []
    return [row for row in rows if row.get(field) == value]
