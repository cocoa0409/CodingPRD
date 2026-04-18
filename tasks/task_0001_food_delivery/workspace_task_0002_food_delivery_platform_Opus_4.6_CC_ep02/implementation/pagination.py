from errors import APIError


def parse_pagination_params(args):
    try:
        limit = int(args.get("limit", 10))
    except (ValueError, TypeError):
        raise APIError("ERR_VALIDATION", "limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (ValueError, TypeError):
        raise APIError("ERR_VALIDATION", "offset must be an integer")

    if limit < 1 or limit > 100:
        raise APIError("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset < 0:
        raise APIError("ERR_VALIDATION", "offset must be non-negative")

    return limit, offset


def paginate(items, limit, offset):
    total_count = len(items)
    page = items[offset : offset + limit]
    has_more = (offset + limit) < total_count
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
