"""List-endpoint helper: sort by creation order, paginate, envelope."""

from db import pub
from middleware import pagination_params
from response import ok


def list_response(items, status=200, sort_key=None):
    if sort_key is None:
        items = sorted(items, key=lambda o: o["_seq"])
    else:
        items = sorted(items, key=sort_key)
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return ok([pub(o) for o in page], status=status, pagination=pagination)
