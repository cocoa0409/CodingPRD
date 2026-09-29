"""Shared listing / single-record response helpers."""

import envelope
import views
from fields import pagination
from store import paginate, sort_rows


def listing(kind, records, keys):
    limit, offset = pagination()
    ordered = sort_rows(records, keys)
    window, total, has_more = paginate(ordered, limit, offset)
    return envelope.arr(views.dump_all(kind, window), limit, offset, total, has_more)


def single(kind, rec):
    return envelope.obj(views.dump(kind, rec))


def created(kind, rec):
    return envelope.created(views.dump(kind, rec))


def match(rec, field, value):
    return value is None or rec.get(field) == value


def listing_rows(kind, ordered):
    """Pagination over rows the caller has already put in their pinned order."""
    limit, offset = pagination()
    window, total, has_more = paginate(ordered, limit, offset)
    return envelope.arr(views.dump_all(kind, window), limit, offset, total, has_more)
