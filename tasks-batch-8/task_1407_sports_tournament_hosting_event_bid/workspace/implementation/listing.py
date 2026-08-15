"""List-endpoint helper: sort, paginate (limit/offset), wrap in the envelope."""

from middleware import pagination_params
from response import ok


def list_response(items, serialize, sort_key=None, status=200):
    if sort_key is not None:
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
    return ok([serialize(o) for o in page], status=status, pagination=pagination)
