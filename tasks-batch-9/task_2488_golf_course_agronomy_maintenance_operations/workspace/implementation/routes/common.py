"""Shared list/pagination plumbing for the route modules."""

from envelope import ok_list
from validators import paginate, pagination


def sorted_by_creation(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def list_response(records, projector, page=None, sort_key=None, reverse=False):
    if page is None:
        page = pagination()
    limit, offset = page
    if sort_key is None:
        ordered = sorted_by_creation(records)
    else:
        ordered = sorted(records, key=sort_key, reverse=reverse)
    items, meta = paginate(ordered, limit, offset)
    return ok_list([projector(item) for item in items], meta)
